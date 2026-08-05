"""Вкладка модов: общие настройки модов (не привязана к конкретному пресету).

Дерево по источникам (Steam / GitHub / локальные папки) либо плоский
сортируемый список — переключается кнопкой «Вид».

Колонки: Название мода | @папка (серым) | Размер | PBO | Серверный | Сорсы |
Изменён | Ребилд. «Серверный» — глобальный признак мода (подсказка при
подключении, см. ui/connect_mods_dialog.py), а не состояние в конкретном
пресете — выбор модов для пресета теперь делается отдельным окном
«Подключить моды» с главной страницы. Свои флаги (название + цвет, см.
ui/mod_flags_dialog.py) назначаются через ПКМ по моду и красят имя мода в
списках. В списочном режиме клик по заголовку колонки сортирует по ней.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import os
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QSize
from PySide6.QtGui import QColor, QFont, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidgetItem,
    QHeaderView,
    QMenu,
    QFileDialog,
    QAbstractItemView,
    QScrollArea,
    QListWidgetItem,
)
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    TransparentToolButton,
    TreeWidget,
    ListWidget,
    ComboBox,
    SearchLineEdit,
    BodyLabel,
    CaptionLabel,
    CheckBox,
    HyperlinkLabel,
    InfoBar,
    InfoBarPosition,
    IndeterminateProgressRing,
    FluentIcon as FIF,
    qconfig,
)

from core import deps, packer, packlog, steam_api, steam_urls
from core.launcher import dayz_running
from core import i18n
from core.i18n import tr
from core.mods import (
    ModRegistry,
    ModInfo,
    SOURCE_STEAM,
    SOURCE_LOCAL,
    SOURCE_GITHUB,
    sort_key as mods_sort_key,
    validate_mod_dir,
    format_size,
    load_flag_defs,
)
from ui.mod_flags_dialog import (
    ModFlagsDialog,
    FlagAssignDialog,
    flag_icon,
    style_checkbox_by_flags,
    style_list_item_by_flags,
    _swatch_icon,
)
from ui import packing_log
from ui.theme import ThemedDialog

if TYPE_CHECKING:
    from ui.packing_log import PackingLog
from core.presets import ModPreset
from core.settings import Settings

(COL_NAME, COL_FOLDER, COL_SIZE, COL_PBO, COL_SERVER, COL_SOURCES, COL_MODIFIED, COL_REBUILD) = range(8)
_GREY = QColor("#888888")
_ORANGE = QColor("#e08f00")
_GREEN = QColor("#2e7d32")
# колонки, у которых сортировка идёт не по тексту ячейки, а по значению,
# сохранённому в UserRole+1 (числа для Размер/PBO/Дата изменения, bool-int
# для Серверный, а для Мод — пара (не библиотека?, имя), чтобы библиотеки по
# умолчанию (сортировка по Мод, по умолчанию восходящая) шли первыми)
_KEYED_COLS = (COL_NAME, COL_SIZE, COL_PBO, COL_SERVER, COL_MODIFIED)


class ModTreeItem(QTreeWidgetItem):
    """Сортирует колонки из _KEYED_COLS по значению из UserRole+1, а не по тексту."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        col = tree.sortColumn() if tree else 0
        if col in _KEYED_COLS:
            a = self.data(col, Qt.ItemDataRole.UserRole + 1)
            b = other.data(col, Qt.ItemDataRole.UserRole + 1)
            if a is not None and b is not None:
                return a < b
        return self.text(col).lower() < other.text(col).lower()


class RebuildWorker(QThread):
    """Пересборка всех сорсов мода по кнопке «Ребилд» (не только устаревших)."""

    done = Signal(bool, str)
    source_start = Signal(str)  # имя pbo — строка таблицы переходит в [packing]
    source_done = Signal(str, bool, int, int, int)  # имя pbo, успех, мс, warnings, errors

    def __init__(self, settings: Settings, mod: ModInfo, sources: list[str], parent=None):
        super().__init__(parent)
        self.settings = settings
        self.mod = mod
        self.sources = sources

    def run(self) -> None:
        for src in self.sources:
            name = packer.pbo_for_source(self.mod, src).name
            self.source_start.emit(name)
            t0 = time.monotonic()
            ok, output = packer.pack_source_auto(self.settings, self.mod, src)
            w, e = packlog.counts(Path(src).name)
            self.source_done.emit(name, ok, int((time.monotonic() - t0) * 1000), w, e)
            if not ok:
                self.done.emit(False, output[-2000:])
                return
        self.done.emit(True, "")


class ScanWorker(QThread):
    """Обход папок модов в фоне.

    Реестр собирается в новый экземпляр, а не правится существующий: пока идёт
    обход, старым продолжают пользоваться списки на экране, и подменять его
    из чужого потока нельзя. Готовый отдаётся сигналом, главное окно меняет
    ссылку у себя.
    """

    progress = Signal(str)  # имя мода, который сейчас читается
    done = Signal(object)  # ModRegistry либо None, если отменили

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        registry = ModRegistry(self.settings)
        try:
            registry.scan(progress=self.progress.emit, cancel=lambda: self._cancelled)
        except OSError:
            # диск отвалился прямо во время обхода — оставляем прежний реестр
            self.done.emit(None)
            return
        self.done.emit(None if self._cancelled else registry)


class StaleCheckWorker(QThread):
    """Проверка актуальности Steam-модов: сравнивает time_updated в Workshop
    с локальной датой изменения файлов мода. Публичный эндпоинт, ключ не нужен."""

    checked = Signal(object, bool)  # mod, outdated

    def __init__(self, mods: list[ModInfo], parent=None):
        super().__init__(parent)
        self.mods = mods

    def run(self) -> None:
        # один запрос на всю пачку, а не по запросу на мод: при недоступной
        # сети иначе выходит N таймаутов подряд, и воркер живёт минутами
        try:
            times = steam_api.times_updated([m.workshop_id for m in self.mods])
        except Exception:  # noqa: BLE001 — сеть/парсинг не должны ронять UI
            return
        for mod in self.mods:
            remote = times.get(mod.workshop_id, 0)
            if not remote:
                continue
            # запас 60с на расхождение часов/времени записи на диск
            self.checked.emit(mod, remote > mod.mtime + 60)


class DependencyResolveWorker(QThread):
    """Обход графа зависимостей в фоне: для Steam-модов он ходит в сеть,
    а глубина заранее неизвестна, так что блокировать UI нельзя."""

    done = Signal(object)  # deps.DepResult

    def __init__(self, roots: list[ModInfo], registry: ModRegistry, api_key: str, parent=None):
        super().__init__(parent)
        self.roots = roots
        self.registry = registry
        self.api_key = api_key

    def run(self) -> None:
        try:
            res = deps.resolve(self.roots, self.registry, self.api_key)
        except Exception:  # noqa: BLE001 — сеть/парсинг не должны ронять UI
            res = deps.DepResult()
        self.done.emit(res)


class DependencyDialog(ThemedDialog):
    """Всё недостающее для подключаемых модов — одним списком.

    Показывает результат полного обхода графа, а не один его уровень: моды из
    реестра идут с галками и подключаются, отсутствующие — серыми. У воркшопных
    есть ссылка на страницу (скачать за пользователя нельзя, подписка делается
    только в клиенте Steam), у локальных её нет — о таком моде известен лишь
    ключ. «Игнорировать» — исходные моды всё равно останутся подключёнными.
    """

    def __init__(self, roots: list[ModInfo], res, parent=None):
        super().__init__(parent)
        names = ", ".join(m.name for m in roots[:3])
        if len(roots) > 3:
            names += f" (+{len(roots) - 3})"
        self.setWindowTitle(tr("mods.deps_title", "Зависимости мода «{m}»", m=names))
        self.resize(520, 380)
        self._rows: list[tuple[ModInfo, CheckBox]] = []

        layout = QVBoxLayout(self)
        hint = BodyLabel(tr("mods.deps_hint", "Для работы «{m}» также необходимо следующее:", m=names))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # список может быть длинным: цепочка зависимостей разворачивается вглубь
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        inner = QWidget()
        inner.setObjectName("depsList")
        inner.setStyleSheet("QWidget#depsList{background:transparent;}")
        box = QVBoxLayout(inner)
        box.setContentsMargins(0, 0, 0, 0)

        flag_defs = {d.id: d for d in load_flag_defs()}
        # порядок обхода графа зависимостей случаен для глаза — приводим к
        # тому же виду, что и остальные списки модов
        for mod in sorted(res.found, key=mods_sort_key):
            cb = CheckBox(mod.name)
            cb.setChecked(True)
            style_checkbox_by_flags(cb, mod, flag_defs)
            box.addWidget(cb)
            self._rows.append((mod, cb))
        for dep_id in res.missing_workshop:
            row = QHBoxLayout()
            cb = CheckBox(tr("mods.deps_missing", "{id} — не подписан", id=dep_id))
            cb.setChecked(False)
            cb.setEnabled(False)
            row.addWidget(cb, 1)
            link = HyperlinkLabel(parent=self)
            link.setUrl(QUrl(steam_urls.workshop_item(dep_id)))
            link.setText(tr("mods.deps_open_workshop", "Открыть в Workshop"))
            row.addWidget(link)
            box.addLayout(row)
        for key in res.missing_local:
            cb = CheckBox(tr("mods.deps_local_missing", "{k} — не найден", k=key))
            cb.setChecked(False)
            cb.setEnabled(False)
            box.addWidget(cb)
        box.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        if res.missing_workshop:
            note = CaptionLabel(
                tr(
                    "mods.deps_note",
                    "Не подписанные моды нужно сначала подписать в Steam — "
                    "ссылка откроет страницу мода. После подписки и скачивания "
                    "нажмите «Обновить» на вкладке модов, чтобы подключить их.",
                )
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        btns = QHBoxLayout()
        b_ignore = PushButton(tr("mods.deps_ignore", "Игнорировать"))
        b_ignore.clicked.connect(self.reject)
        b_connect = PrimaryPushButton(FIF.LINK, tr("mods.deps_connect", "Подключить"))
        b_connect.setEnabled(bool(res.found))
        b_connect.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(b_ignore)
        btns.addWidget(b_connect)
        layout.addLayout(btns)

    def selected_mods(self) -> list[ModInfo]:
        return [m for m, cb in self._rows if cb.isChecked()]


class DependencyPickerDialog(ThemedDialog):
    """Ручной выбор зависимостей локального мода — из какого чек-листа при
    подключении мода в пресет будут предложены недостающие (см.
    ModsPanel._check_local_dependencies)."""

    def __init__(self, mod: ModInfo, registry: ModRegistry, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.setWindowTitle(tr("mods.deps_edit_title", "Зависимости мода «{m}»", m=mod.name))
        self.resize(420, 520)

        layout = QVBoxLayout(self)
        hint = BodyLabel(
            tr(
                "mods.deps_edit_hint",
                "Отметьте моды, без которых «{m}» не должен подключаться. "
                "При добавлении «{m}» в пресет их предложат подключить "
                "автоматически.",
                m=mod.name,
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._flag_defs = {d.id: d for d in load_flag_defs()}
        own_key = mod.folder_name.lower()
        self._checked: set[str] = set(mod.dependencies)
        self._all_mods = [m for m in registry.all() if m.folder_name.lower() != own_key]

        filter_row = QHBoxLayout()
        self.search = SearchLineEdit()
        self.search.setPlaceholderText(tr("mods.search_ph", "Фильтр по названию…"))
        self.search.textChanged.connect(lambda _t: self._rebuild_list())
        filter_row.addWidget(self.search, 1)
        self.tag_combo = ComboBox()
        self.tag_combo.addItem(tr("connect.tag_all", "Все теги"), userData="")
        for d in self._flag_defs.values():
            icon = flag_icon(d) or _swatch_icon(d.color)
            self.tag_combo.addItem(d.name, icon=icon, userData=d.id)
        self.tag_combo.currentIndexChanged.connect(lambda _i: self._rebuild_list())
        filter_row.addWidget(self.tag_combo)
        layout.addLayout(filter_row)

        self.sort_combo = ComboBox()
        self.sort_combo.addItem(tr("mods.sort_name", "Сортировка: по имени"), userData="name")
        self.sort_combo.addItem(tr("mods.sort_tag", "Сортировка: по тегу"), userData="tag")
        self.sort_combo.currentIndexChanged.connect(lambda _i: self._rebuild_list())
        layout.addWidget(self.sort_combo)

        self.lst = ListWidget()
        layout.addWidget(self.lst, 1)
        self._rebuild_list()

        btns = QHBoxLayout()
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_save = PrimaryPushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        b_save.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(b_cancel)
        btns.addWidget(b_save)
        layout.addLayout(btns)

    def _rebuild_list(self) -> None:
        # запоминаем текущие галки (в т.ч. по скрытым сейчас фильтром строкам) —
        # чтобы поиск/тег/сортировка не теряли уже отмеченное
        for i in range(self.lst.count()):
            item = self.lst.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked:
                self._checked.add(key)
            else:
                self._checked.discard(key)

        q = self.search.text().strip().lower()
        tag = self.tag_combo.currentData()
        mods = [m for m in self._all_mods if not q or q in m.name.lower()]
        if tag:
            mods = [m for m in mods if tag in m.flags]
        by_tag = self.sort_combo.currentData() == "tag"

        def sort_key(m):
            """Уже отмеченные зависимости — всегда наверху.

            Окно про то, от чего зависит мод: выбранное должно быть перед
            глазами, а не теряться среди сотни остальных. Флаги идут следом —
            здесь они менее важны.
            """
            picked = 0 if m.folder_name.lower() in self._checked else 1
            if by_tag:
                ids = [f for f in m.flags if f in self._flag_defs]
                tag_name = self._flag_defs[ids[0]].name.lower() if ids else "￿"
                return (picked, tag_name, m.name.lower())
            return (picked,) + mods_sort_key(m)

        mods = sorted(mods, key=sort_key)

        self.lst.clear()
        for other in mods:
            key = other.folder_name.lower()
            item = QListWidgetItem(other.name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in self._checked else Qt.CheckState.Unchecked)
            style_list_item_by_flags(item, other, self._flag_defs)
            self.lst.addItem(item)

    def selected_keys(self) -> list[str]:
        for i in range(self.lst.count()):
            item = self.lst.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked:
                self._checked.add(key)
            else:
                self._checked.discard(key)
        return list(self._checked)


_MAX_RECENT_DIRS = 8


def _remember_recent_dirs(settings: Settings | None, picked: list[str]) -> None:
    if not settings or not picked:
        return
    parents = [str(Path(p).parent) for p in picked]
    settings.recent_source_dirs = parents + settings.recent_source_dirs
    # без дублей, сохраняя порядок (последние выбранные — впереди)
    seen: set[str] = set()
    deduped = []
    for d in settings.recent_source_dirs:
        if d not in seen:
            seen.add(d)
            deduped.append(d)
    settings.recent_source_dirs = deduped[:_MAX_RECENT_DIRS]
    settings.save()


def pick_source_directory(parent, caption: str, settings: Settings | None = None) -> str:
    """Нативный выбор папки Windows с адресной строкой и ручным вводом пути."""
    candidates = [*(settings.recent_source_dirs if settings else []), "P:/", str(Path.home())]
    start = next((path for path in candidates if Path(path).is_dir()), "")
    picked = QFileDialog.getExistingDirectory(parent, caption, start, QFileDialog.Option.ShowDirsOnly)
    if picked:
        _remember_recent_dirs(settings, [picked])
    return picked


class SourcesDialog(ThemedDialog):
    """Папки сорсов локального мода (для запаковщика)."""

    def __init__(self, mod: ModInfo, settings: Settings | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("mods.sources_title", "Сорсы мода {m}", m=mod.name))
        self.resize(560, 300)
        layout = QVBoxLayout(self)
        hint = BodyLabel(
            tr(
                "mods.sources_hint",
                "Одна папка сорсов = один PBO в addons. Запаковщик сравнивает даты файлов сорсов с датой PBO.",
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.lst = ListWidget()
        self.lst.addItems(mod.sources)
        layout.addWidget(self.lst, 1)
        btns = QHBoxLayout()
        b_add = PushButton(FIF.ADD, tr("mods.sources_add", "Добавить папку…"))
        b_add.setToolTip(tr("mods.sources_add_tip", "Для нескольких PBO добавьте каждую папку отдельно."))
        b_del = PushButton(FIF.REMOVE, tr("mods.sources_del", "Убрать выбранную"))
        b_ok = PrimaryPushButton("OK")
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(lambda: self.lst.takeItem(self.lst.currentRow()))
        b_ok.clicked.connect(self.accept)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addStretch(1)
        btns.addWidget(b_ok)
        layout.addLayout(btns)

    def _add(self) -> None:
        existing = {self.lst.item(i).text() for i in range(self.lst.count())}
        picked = pick_source_directory(self, tr("mods.sources_pick", "Папка сорсов"), self.settings)
        if picked and picked not in existing:
            self.lst.addItem(picked)

    def sources(self) -> list[str]:
        return [self.lst.item(i).text() for i in range(self.lst.count())]


class HiddenModsDialog(ThemedDialog):
    """Список модов, убранных из списка вручную (settings.excluded_mods) — можно вернуть.
    Показывает настоящее имя/источник мода, а не голый ключ — hidden передаётся из
    ModRegistry.hidden (см. scan()); для ключей без соответствия (мод давно
    удалён с диска) показывается сам ключ."""

    def __init__(self, excluded_mods: list[str], hidden: dict[str, ModInfo], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mods.hidden_title", "Скрытые моды"))
        self.resize(400, 320)
        self._boxes: list[tuple[str, CheckBox]] = []
        layout = QVBoxLayout(self)
        hint = BodyLabel(tr("mods.hidden_hint", "Отметьте моды, которые нужно вернуть в список."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        if not excluded_mods:
            layout.addWidget(CaptionLabel(tr("mods.hidden_empty", "Скрытых модов нет.")))
        # скрытые хранятся в порядке скрытия — показываем в общем порядке
        for key in sorted(excluded_mods, key=lambda k: mods_sort_key(hidden[k]) if k in hidden else (2, (), k)):
            mod = hidden.get(key)
            if mod:
                src = {SOURCE_STEAM: "Steam", SOURCE_LOCAL: "Локальный", SOURCE_GITHUB: "GitHub"}.get(
                    mod.source, mod.source
                )
                cb = CheckBox(f"{mod.name}  ({src})")
                cb.setToolTip(mod.path)
            else:
                cb = CheckBox(tr("mods.hidden_gone", "{k} — не найден на диске", k=key))
            layout.addWidget(cb)
            self._boxes.append((key, cb))
        layout.addStretch(1)
        btns = QHBoxLayout()
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(tr("mods.hidden_restore", "Вернуть отмеченные"))
        b_ok.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        layout.addLayout(btns)

    def selected_keys(self) -> list[str]:
        return [k for k, cb in self._boxes if cb.isChecked()]


class SetsDialog(ThemedDialog):
    """Выбор одного или нескольких сохранённых наборов модов — их подключённые
    моды объединяются (без дублей) в текущий пресет."""

    def __init__(self, sets: list[ModPreset], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mods.sets_title", "Наборы модов"))
        self.resize(360, 320)
        self._boxes: list[tuple[ModPreset, CheckBox]] = []
        layout = QVBoxLayout(self)
        hint = BodyLabel(tr("mods.sets_hint", "Можно выбрать сразу несколько наборов — их моды объединятся."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        for mp in sets:
            cb = CheckBox(mp.name)
            layout.addWidget(cb)
            self._boxes.append((mp, cb))
        layout.addStretch(1)
        btns = QHBoxLayout()
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(tr("mods.sets_apply", "Выбрать"))
        b_ok.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        layout.addLayout(btns)

    def selected(self) -> list[ModPreset]:
        return [mp for mp, cb in self._boxes if cb.isChecked()]


class ModsPanel(QWidget):
    presets_changed = Signal()  # пресеты правились на диске — окну пора перечитать

    def __init__(self, parent=None):
        super().__init__(parent)
        self.registry: ModRegistry | None = None
        self.settings: Settings | None = None
        self.log_cb: Callable[..., None] | None = None
        self.pack_table: PackingLog | None = None
        self.packed_cb: Callable[[list[str]], None] | None = None
        self._building = False
        self._flat_view = True
        self._rebuild_workers: list[RebuildWorker] = []  # держим ссылки, иначе поток соберёт GC
        self._stale_worker: StaleCheckWorker | None = None
        self._scan_worker: ScanWorker | None = None
        # кому сообщить, что реестр пересобран: главное окно держит свою ссылку
        self.registry_changed: Callable[[ModRegistry], None] | None = None
        self._misc_workers: list[QThread] = []  # разовые проверки из контекстного меню
        self._flag_defs: dict = {}  # id -> ModFlagDef, обновляется в _rebuild()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        top = QHBoxLayout()
        self.b_refresh = PushButton(FIF.SYNC, tr("mods.refresh", "Обновить"))
        self.b_refresh.clicked.connect(self._refresh_clicked)
        b_refresh = self.b_refresh
        b_add_dir = PushButton(FIF.FOLDER_ADD, tr("mods.add_local", "Добавить локальные моды"))
        b_add_dir.setToolTip(tr("mods.add_dir_tip", "Папка с @модами или одиночная @папка мода."))
        b_add_dir.clicked.connect(self._add_folder)
        b_hidden = PushButton(FIF.VIEW, tr("mods.hidden_btn", "Скрытые моды…"))
        b_hidden.setToolTip(
            tr("mods.hidden_btn_tip", "Моды, убранные из списка через контекстное меню «Убрать из списка».")
        )
        b_hidden.clicked.connect(self._open_hidden_mods)
        b_flags = PushButton(FIF.PALETTE, tr("mods.flags_btn", "Флаги…"))
        b_flags.setToolTip(
            tr("mods.flags_btn_tip", "Свои метки модов (название + цвет) — назначаются через ПКМ по моду.")
        )
        b_flags.clicked.connect(self._open_flags)
        for b in (b_refresh, b_add_dir, b_hidden, b_flags):
            top.addWidget(b)
        top.addStretch(1)
        # что именно читается прямо сейчас — иначе кнопка «Отменить» без
        # признаков жизни выглядит как зависание
        self.status = CaptionLabel("")
        self.status.setStyleSheet("color:#888888;")
        top.addWidget(self.status)
        layout.addLayout(top)

        # Поиск и переключатель вида — в одной строке, прямо над заголовками
        # колонок: кнопка «Вид» физически рядом с тем, чем она управляет
        # (сортировкой по клику на заголовок).
        search_row = QHBoxLayout()
        self.search = SearchLineEdit()
        self.search.setPlaceholderText(tr("mods.search_ph", "Фильтр по названию…"))
        self.search.textChanged.connect(self._apply_filter)
        self.b_view = PushButton(FIF.VIEW, tr("mods.view_list", "Вид: Список"))
        self.b_view.setToolTip(
            tr(
                "mods.view_tip",
                "Переключить между деревом по источникам и плоским списком "
                "с сортировкой по клику на заголовок колонки.",
            )
        )
        self.b_view.clicked.connect(self._toggle_view)
        search_row.addWidget(self.b_view)
        search_row.addWidget(self.search, 1)
        layout.addLayout(search_row)

        self.tree = TreeWidget(self)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels(
            [
                tr("mods.col_name", "Мод"),
                tr("mods.col_folder", "Папка"),
                tr("mods.col_size", "Размер"),
                tr("mods.col_pbo", "PBO"),
                tr("mods.col_server", "Серверный"),
                tr("mods.col_sources", "Сорсы"),
                tr("mods.col_modified", "Изменён"),
                "",
            ]
        )
        self.tree.headerItem().setToolTip(COL_REBUILD, tr("mods.col_rebuild", "Ребилд"))
        hdr = self.tree.header()
        # «Мод» — по содержимому (имена короткие и осмысленные, обрезать нечего),
        # тянется «Папка»: там длинные пути, которым лишняя ширина полезнее
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_PBO, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_SERVER, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_SOURCES, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_MODIFIED, QHeaderView.ResizeMode.ResizeToContents)
        # без текста в заголовке колонка не раздувается шириной слова "Ребилд" —
        # фиксированная ширина точно под саму кнопку/спиннер (см. _REBUILD_CELL_SIZE)
        hdr.setSectionResizeMode(COL_REBUILD, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(COL_REBUILD, self._REBUILD_CELL_SIZE + 8)
        # без явной инициализации Qt отдаёт sortIndicatorOrder() == Descending
        # ещё до первого клика по заголовку — это переворачивало сортировку
        # по умолчанию (подключённые моды оказывались в конце, а не в начале)
        hdr.setSortIndicator(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(self._item_dbl)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        layout.addWidget(self.tree, 1)

        hint = CaptionLabel(
            tr(
                "mods.hint",
                "Здесь — общие настройки модов, не привязанные к конкретному пресету. "
                "«Серверный» — мод подключается в -serverMod, а не в -mod, в окне "
                "«Подключить моды». Свои флаги (название + цвет имени) — кнопка «Флаги…», "
                "назначение — правый клик по моду. Двойной клик по «Сорсы» — привязать "
                "сорсы локального мода для запаковки. В режиме списка клик по заголовку "
                "колонки сортирует по ней.",
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Иконки флагов рисуются под текущую тему в момент сборки списка, так
        # что при переключении темы на лету они остались бы прежнего цвета —
        # чёрные на тёмном фоне. Перестраиваем дерево.
        qconfig.themeChanged.connect(lambda _t: self._rebuild())

    # ---------------------------------------------------------------- контекст

    def set_context(self, registry: ModRegistry, settings: Settings | None = None) -> None:
        self.registry = registry
        if settings is not None:
            self.settings = settings
        self._rebuild()
        self._check_stale()

    def refresh(self) -> None:
        """Пересканировать моды. Обход идёт в фоне — список остаётся живым.

        Читается размер и дата каждого файла каждого мода; на прогретом кеше
        это десятки миллисекунд, на холодном или на внешнем диске — секунды.
        Держать на этом главный поток нельзя: обновление зовётся после каждой
        пересборки мода.
        """
        if not self.settings or (self._scan_worker and self._scan_worker.isRunning()):
            return
        self._scan_worker = ScanWorker(self.settings, self)
        self._scan_worker.progress.connect(self._scan_progress)
        self._scan_worker.done.connect(self._scan_done)
        self.b_refresh.setText(tr("mods.refresh_busy", "Отменить"))
        self.b_refresh.setIcon(FIF.CLOSE)
        self._scan_worker.start()

    def _scan_progress(self, name: str) -> None:
        self.status.setText(tr("mods.scanning", "Обновление: {n}…", n=name))

    def _scan_done(self, registry: ModRegistry | None) -> None:
        self.b_refresh.setText(tr("mods.refresh", "Обновить"))
        self.b_refresh.setIcon(FIF.SYNC)
        self.status.setText("")
        if registry is None:  # отменено или диск отвалился
            return
        self.registry = registry
        if self.registry_changed:
            self.registry_changed(registry)
        self._rebuild()
        self._check_stale()

    def _refresh_clicked(self) -> None:
        """Одна кнопка на два действия: пока идёт обход — отмена."""
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            return
        self.refresh()

    def _check_stale(self) -> None:
        """Фоновая проверка актуальности всех Steam-модов относительно Workshop."""
        if not self.registry or (self._stale_worker and self._stale_worker.isRunning()):
            return
        steam_mods = [m for m in self.registry.all() if m.source == SOURCE_STEAM and m.valid]
        if not steam_mods:
            return
        self._stale_worker = StaleCheckWorker(steam_mods, self)
        self._stale_worker.checked.connect(self._on_stale_checked)
        self._stale_worker.start()

    def _on_stale_checked(self, mod: ModInfo, outdated: bool) -> None:
        if mod.outdated == outdated:
            return
        mod.outdated = outdated
        for item in self._iter_mod_items():
            if self._item_mod(item) is mod:
                self._apply_outdated_mark(item, mod)
                break

    def _apply_outdated_mark(self, item: QTreeWidgetItem, mod: ModInfo) -> None:
        """Точечно обновляет строку мода после фоновой проверки актуальности —
        без полной пересборки дерева (не сбивает сортировку/скролл)."""
        name = mod.name
        if mod.duplicate_of_steam:
            name += "  " + tr("mods.dup", "(есть дубль в Workshop)")
        if mod.outdated:
            name += "  " + tr("mods.outdated", "(устарел)")
        if not mod.valid:
            name = "⚠ " + name
        item.setText(COL_NAME, name)
        if not mod.valid:
            item.setForeground(COL_NAME, QColor("#d32f2f"))
        elif mod.outdated:
            item.setForeground(COL_NAME, _ORANGE)
        else:
            item.setData(COL_NAME, Qt.ItemDataRole.ForegroundRole, None)
        tip = mod.problem or mod.name
        if mod.outdated:
            tip += "\n" + tr("mods.outdated_tip", "В Steam Workshop есть более новая версия мода.")
        item.setToolTip(COL_NAME, tip)

    # ---------------------------------------------------------------- дерево

    def _expanded_groups(self) -> set[str]:
        out = set()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            if g is None:
                continue
            if g.isExpanded():
                out.add(g.text(COL_NAME).rsplit(" (", 1)[0])
        return out

    def _toggle_view(self) -> None:
        self._flat_view = not self._flat_view
        self.b_view.setText(
            tr("mods.view_list", "Вид: Список") if self._flat_view else tr("mods.view_tree", "Вид: Дерево")
        )
        self._rebuild(reset_expand=True)

    def _rebuild(self, reset_expand: bool = False) -> None:
        expanded = None if reset_expand else (self._expanded_groups() or None)
        # запоминаем текущую сортировку, чтобы пересборка одного мода (refresh()
        # после ребилда) не сбрасывала список обратно на «по названию»
        hdr = self.tree.header()
        sort_col = hdr.sortIndicatorSection() if self._flat_view else COL_NAME
        sort_order = hdr.sortIndicatorOrder() if self._flat_view else Qt.SortOrder.AscendingOrder
        # прокрутка и выделенная строка: список пересобирается целиком после
        # каждого ребилда мода, и без этого страница уезжала в начало — а мод,
        # который только что пересобрали, обычно не первый в списке
        scroll = self.tree.verticalScrollBar().value()
        cur = self._item_mod(self.tree.currentItem()) if self.tree.currentItem() else None
        cur_key = cur.folder_name.lower() if cur else ""
        self._building = True
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        if not self.registry:
            self._building = False
            return
        # флаги грузятся один раз на всю пересборку — не на каждый мод отдельно
        self._flag_defs = {d.id: d for d in load_flag_defs()}

        if self._flat_view:
            for mod in self.registry.all():
                item = self._make_mod_item(mod)
                self.tree.addTopLevelItem(item)
                self._maybe_add_rebuild_button(item, mod)
            # сортировка по клику на заголовок — только здесь, в плоском списке;
            # в дереве заголовки специально делаем некликабельными (см. ниже),
            # чтобы клик по ним не выглядел «сломанным»
            hdr.setSectionsClickable(True)
            hdr.setSortIndicatorShown(True)
            self.tree.setSortingEnabled(True)
            self.tree.sortItems(sort_col, sort_order)
        else:
            hdr.setSectionsClickable(False)
            hdr.setSortIndicatorShown(False)
            groups: dict[str, list[ModInfo]] = {}
            for mod in self.registry.all():
                groups.setdefault(mod.group or tr("mods.local", "Локальный"), []).append(mod)

            def group_rank(name: str):
                if name == "Steam":
                    return (0, name)
                if name == "GitHub":
                    return (1, name)
                return (2, name.lower())

            for gname in sorted(groups, key=group_rank):
                mods = groups[gname]
                gitem = QTreeWidgetItem([f"{gname} ({len(mods)})"] + [""] * 7)
                gitem.setFlags(Qt.ItemFlag.ItemIsEnabled)
                font = QFont()
                font.setBold(True)
                gitem.setFont(COL_NAME, font)
                # растягиваем заголовок группы на всю строку — иначе при узкой
                # колонке «Мод» жирный текст обрезается многоточием
                gitem.setFirstColumnSpanned(True)
                self.tree.addTopLevelItem(gitem)
                for mod in mods:
                    item = self._make_mod_item(mod)
                    gitem.addChild(item)
                    self._maybe_add_rebuild_button(item, mod)
                gitem.setExpanded(expanded is None or gname in expanded)
        self._building = False
        self._apply_filter(self.search.text())
        self._restore_view(scroll, cur_key)

    def _restore_view(self, scroll: int, cur_key: str) -> None:
        """Возвращает прокрутку и выделение после пересборки списка."""
        if cur_key:
            for item in self._iter_mod_items():
                mod = self._item_mod(item)
                if mod and mod.folder_name.lower() == cur_key:
                    # без scrollTo: прокрутку восстанавливаем сами, а он бы
                    # подвинул её к строке и свёл всю затею на нет
                    self.tree.setCurrentItem(item)
                    break
        bar = self.tree.verticalScrollBar()
        bar.setValue(min(scroll, bar.maximum()))

    def _make_mod_item(self, mod: ModInfo) -> ModTreeItem:
        name = mod.name
        if mod.duplicate_of_steam:
            name += "  " + tr("mods.dup", "(есть дубль в Workshop)")
        if mod.outdated:
            name += "  " + tr("mods.outdated", "(устарел)")
        if not mod.valid:
            name = "⚠ " + name
        item = ModTreeItem(
            [
                name,
                mod.folder_name,
                format_size(mod.size_bytes),
                str(mod.pbo_count),
                "",
                self._sources_text(mod),
                self._modified_text(mod.mtime),
                "",
            ]
        )
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(COL_SERVER, Qt.CheckState.Checked if mod.is_server else Qt.CheckState.Unchecked)
        # ключ сортировки: Серверный — по чекбоксу
        # ключ по имени с рангом флага впереди: сортировка по «Мод» —
        # она же сортировка по умолчанию — держит помеченные сверху
        item.setData(COL_NAME, Qt.ItemDataRole.UserRole + 1, mods_sort_key(mod))
        item.setData(COL_SERVER, Qt.ItemDataRole.UserRole + 1, 0 if mod.is_server else 1)
        item.setForeground(COL_FOLDER, _GREY)
        item.setForeground(COL_SOURCES, self._sources_color(mod))
        if mod.sources:
            item.setToolTip(COL_SOURCES, "\n".join(mod.sources))
        item.setForeground(COL_SIZE, _GREY)
        item.setForeground(COL_PBO, _GREY)
        item.setData(COL_SIZE, Qt.ItemDataRole.UserRole + 1, mod.size_bytes)
        item.setData(COL_PBO, Qt.ItemDataRole.UserRole + 1, mod.pbo_count)
        if mod.pbo_names:
            item.setToolTip(COL_PBO, "\n".join(mod.pbo_names))
        # оформление имени по флагам: цвет/иконка — от первого назначенного,
        # начертание (жирный/курсив/подчёркнутый) — объединяется по всем сразу;
        # невалиден/устарел по цвету всегда важнее пометки флагом
        flag_ids = [fid for fid in mod.flags if fid in self._flag_defs]
        flag_names = [self._flag_defs[fid].name for fid in flag_ids]
        if flag_ids:
            flag_defs = [self._flag_defs[fid] for fid in flag_ids]
            font = item.font(COL_NAME)
            font.setBold(any(d.bold for d in flag_defs))
            font.setItalic(any(d.italic for d in flag_defs))
            font.setUnderline(any(d.underline for d in flag_defs))
            item.setFont(COL_NAME, font)
            item.setForeground(COL_NAME, QColor(flag_defs[0].color))
            icon = flag_icon(flag_defs[0])
            if icon:
                item.setIcon(COL_NAME, icon)
        if mod.outdated:
            item.setForeground(COL_NAME, _ORANGE)
        if not mod.valid:
            item.setForeground(COL_NAME, QColor("#d32f2f"))
        # полное название мода вместо пути — путь и так есть в колонке «Папка»
        # и в подсказках у других колонок; для невалидных — причина проблемы
        tip = mod.problem or mod.name
        if mod.outdated:
            tip += "\n" + tr("mods.outdated_tip", "В Steam Workshop есть более новая версия мода.")
        if flag_names:
            tip += "\n" + tr("mods.flags_tip", "Флаги: {f}", f=", ".join(flag_names))
        item.setToolTip(COL_NAME, tip)
        item.setToolTip(
            COL_SERVER,
            tr("mods.server_tip", "Подключать в -serverMod (только на сервер), а не в -mod, в окне «Подключить моды»."),
        )
        item.setForeground(COL_MODIFIED, _GREY)
        item.setData(COL_MODIFIED, Qt.ItemDataRole.UserRole + 1, mod.mtime)
        item.setData(COL_NAME, Qt.ItemDataRole.UserRole, mod.folder_name.lower())
        return item

    @staticmethod
    def _modified_text(mtime: float) -> str:
        if not mtime:
            return ""
        dt = datetime.fromtimestamp(mtime)
        if i18n.current() == "ru":
            return dt.strftime("%d.%m.%y %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")

    _REBUILD_CELL_SIZE = 22

    def _maybe_add_rebuild_button(self, item: QTreeWidgetItem, mod: ModInfo) -> None:
        """Кнопка «Ребилд» только у модов с привязанными сорсами."""
        if not mod.sources:
            return
        btn = TransparentToolButton(FIF.UPDATE)
        btn.setFixedSize(self._REBUILD_CELL_SIZE, self._REBUILD_CELL_SIZE)
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tr("mods.rebuild_tip", "Пересобрать PBO из всех привязанных сорсов."))
        btn.clicked.connect(lambda _=False, m=mod, it=item: self._rebuild_mod(m, it))
        self.tree.setItemWidget(item, COL_REBUILD, btn)

    def _sources_text(self, mod: ModInfo) -> str:
        # «не заданы» — приглашение их задать, а чужие моды мы не собираем:
        # у воркшопных и скачанных с GitHub сорсов не бывает по определению
        if not mod.can_have_sources:
            return tr("mods.sources_na", "не требуются")
        return tr("mods.sources_set", "Указаны") if mod.sources else tr("mods.no_sources", "не заданы")

    def _sources_color(self, mod: ModInfo) -> QColor:
        if not mod.can_have_sources:
            return _GREY
        return _GREEN if mod.sources else _ORANGE

    def _iter_mod_items(self) -> Iterator[QTreeWidgetItem]:
        """Все строки модов — работает и в режиме дерева, и в плоском списке."""

        def walk(item: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
            if item.data(COL_NAME, Qt.ItemDataRole.UserRole):
                yield item
            for ci in range(item.childCount()):
                child = item.child(ci)
                if child is not None:
                    yield from walk(child)

        for gi in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(gi)
            if item is not None:
                yield from walk(item)

    def _item_mod(self, item: QTreeWidgetItem) -> ModInfo | None:
        key = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        return self.registry.mods.get(key) if (key and self.registry) else None

    # ---------------------------------------------------------------- изменения

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """«Серверный» — глобальный признак мода (не пресета), сохраняется
        сразу в registry.save_flags()."""
        if self._building or not self.registry or column != COL_SERVER:
            return
        mod = self._item_mod(item)
        if not mod:
            return
        mod.is_server = item.checkState(COL_SERVER) == Qt.CheckState.Checked
        self.registry.save_flags()
        # Метка — свойство мода, но подключён он в пресетах списком: -mod или
        # -serverMod. Без переноса мод продолжал бы уходить не в ту строку
        # запуска, и человек видел бы ту же ошибку, ради которой метку и ставил.
        from core.presets import apply_server_flag

        changed = apply_server_flag(mod.name, mod.is_server)
        if changed:
            # молча переписывать чужие пресеты нельзя — говорим, какие именно
            InfoBar.success(
                title=tr(
                    "mods.server_moved",
                    "«{m}» перенесён в {where} в пресетах: {list}",
                    m=mod.name,
                    where=(
                        tr("mods.server_line", "серверные моды")
                        if mod.is_server
                        else tr("mods.client_line", "клиентские моды")
                    ),
                    list=", ".join(changed),
                ),
                content="",
                parent=self,
                duration=6000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            self.presets_changed.emit()

    def _item_dbl(self, item: QTreeWidgetItem, column: int) -> None:
        if column == COL_NAME:
            mod = self._item_mod(item)
            if mod and mod.source == SOURCE_LOCAL:
                self._edit_dependencies(mod)
            return
        if column != COL_SOURCES:
            return
        mod = self._item_mod(item)
        if not mod or not mod.can_have_sources:
            return
        dlg = SourcesDialog(mod, self.settings, self)
        if dlg.exec():
            mod.sources = dlg.sources()
            if self.registry:
                self.registry.save_sources()
            item.setText(COL_SOURCES, self._sources_text(mod))
            if mod.sources:
                self._maybe_add_rebuild_button(item, mod)
            else:
                self.tree.removeItemWidget(item, COL_REBUILD)

    def _apply_filter(self, text: str) -> None:
        q = text.strip().lower()

        def matches(item) -> bool:
            return not q or q in item.text(COL_NAME).lower() or q in item.text(COL_FOLDER).lower()

        if self._flat_view:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item is None:
                    continue
                item.setHidden(not matches(item))
            return
        for gi in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(gi)
            if g is None:
                continue
            visible_children = 0
            for ci in range(g.childCount()):
                child = g.child(ci)
                if child is None:
                    continue
                match = matches(child)
                child.setHidden(not match)
                visible_children += int(match)
            g.setHidden(visible_children == 0)
            if q and visible_children:
                g.setExpanded(True)

    # ---------------------------------------------------------------- папки модов

    def _group_source_dirs(self, gitem: QTreeWidgetItem) -> list[str]:
        """Записи settings.local_mods_dirs, которым соответствует эта группа дерева."""
        if not self.settings:
            return []
        matches: set[str] = set()
        for ci in range(gitem.childCount()):
            child = gitem.child(ci)
            if child is None:
                continue
            mod = self._item_mod(child)
            if not mod:
                continue
            mp = Path(mod.path)
            for d in self.settings.local_mods_dirs:
                dp = Path(d)
                if mp.parent == dp or mp == dp:
                    matches.add(d)
        return list(matches)

    def _tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return
        selected_mods = [m for it in self.tree.selectedItems() if (m := self._item_mod(it))]
        if len(selected_mods) > 1:
            self._bulk_context_menu(selected_mods, pos)
            return
        mod = self._item_mod(item)
        if mod:
            self._mod_context_menu(item, mod, pos)
            return
        # иначе — заголовок группы верхнего уровня (только в режиме дерева;
        # во плоском списке все строки — моды и до сюда код не доходит)
        if item.parent() is not None or not self.settings:
            return
        dirs = self._group_source_dirs(item)
        if not dirs:
            return  # группа не из настроенных папок (Steam/GitHub/легаси-корни)
        menu = QMenu(self)
        act = menu.addAction(tr("mods.remove_dir", "Убрать эту папку из списка локальных модов"))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen != act:
            return
        for d in dirs:
            if d in self.settings.local_mods_dirs:
                self.settings.local_mods_dirs.remove(d)
        self.settings.save()
        self.refresh()

    def _mod_context_menu(self, item: QTreeWidgetItem, mod: ModInfo, pos) -> None:
        menu = QMenu(self)
        act_update = (
            menu.addAction(tr("mods.ctx_check_updates", "Проверить обновления"))
            if mod.source == SOURCE_STEAM and mod.workshop_id
            else None
        )
        act_rebuild = menu.addAction(tr("mods.ctx_rebuild", "Сделать ребилд")) if mod.sources else None
        act_open_mod = menu.addAction(tr("mods.ctx_open_mod", "Открыть расположение мода"))
        act_open_src = (
            menu.addAction(tr("mods.ctx_open_sources", "Открыть расположение сорсов")) if mod.sources else None
        )
        act_open_steam = (
            menu.addAction(tr("mods.ctx_open_steam", "Открыть страницу в Steam"))
            if mod.source == SOURCE_STEAM and mod.workshop_id
            else None
        )
        act_deps = menu.addAction(tr("mods.ctx_deps", "Зависимости…")) if mod.source == SOURCE_LOCAL else None
        act_flags = menu.addAction(tr("mods.ctx_flags", "Флаги…"))
        menu.addSeparator()
        act_remove = menu.addAction(tr("mods.ctx_remove", "Убрать из списка"))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_update:
            self._check_single_mod(mod)
        elif chosen is act_rebuild:
            self._rebuild_mod(mod, item)
        elif chosen is act_open_mod:
            self._open_path(mod.path)
        elif chosen is act_open_src:
            for src in mod.sources:
                self._open_path(src)
        elif chosen is act_open_steam:
            QDesktopServices.openUrl(QUrl(steam_urls.workshop_item(mod.workshop_id)))
        elif chosen is act_deps:
            self._edit_dependencies(mod)
        elif chosen is act_flags:
            self._assign_flags([mod])
        elif chosen is act_remove:
            self._remove_from_list(mod)

    def _bulk_context_menu(self, mods: list[ModInfo], pos) -> None:
        menu = QMenu(self)
        n = len(mods)
        act_flags = menu.addAction(tr("mods.ctx_flags_bulk", "Флаги… ({n})", n=n))
        # обновления есть только у воркшопных: у локальных и скачанных с
        # GitHub спрашивать не у кого
        steam = [m for m in mods if m.source == SOURCE_STEAM and m.workshop_id]
        act_update = (
            menu.addAction(tr("mods.ctx_check_updates_bulk", "Проверить обновления ({n})", n=len(steam)))
            if steam
            else None
        )
        act_open = menu.addAction(tr("mods.ctx_open_mod_bulk", "Открыть расположение модов ({n})", n=n))
        menu.addSeparator()
        act_remove = menu.addAction(tr("mods.ctx_remove_bulk", "Убрать из списка ({n})", n=n))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_flags:
            self._assign_flags(mods)
        elif chosen is act_update:
            for mod in steam:
                self._check_single_mod(mod)
        elif chosen is act_open:
            self._open_paths([m.path for m in mods])
        elif chosen is act_remove:
            self._remove_from_list(mods)

    def _assign_flags(self, mods: list[ModInfo]) -> None:
        if not self.registry:
            return
        dlg = FlagAssignDialog(mods, load_flag_defs(), self.window())
        if not dlg.exec():
            return
        changes = dlg.result_changes()
        if not changes:
            return
        for mod in mods:
            for fid, add in changes.items():
                if add and fid not in mod.flags:
                    mod.flags.append(fid)
                elif not add and fid in mod.flags:
                    mod.flags.remove(fid)
        self.registry.save_flags()
        self._rebuild()

    def _edit_dependencies(self, mod: ModInfo) -> None:
        if not self.registry:
            return
        dlg = DependencyPickerDialog(mod, self.registry, self.window())
        if not dlg.exec():
            return
        mod.dependencies = dlg.selected_keys()
        self.registry.save_dependencies()

    @staticmethod
    def _open_path(path: str) -> None:
        if Path(path).is_dir():
            os.startfile(path)  # noqa: S606 — открытие проводника по своей же папке мода

    @staticmethod
    def _open_paths(paths: list[str]) -> None:
        """Проводник по нескольким модам.

        Одинаковые родительские папки схлопываем: у десятка воркшопных модов
        родитель один, и открывать его десять раз — десять одинаковых окон.
        """
        seen: set[str] = set()
        for path in paths:
            p = Path(path)
            target = str(p.parent) if p.parent.is_dir() else path
            if target in seen:
                continue
            seen.add(target)
            ModsPanel._open_path(target)

    def _check_single_mod(self, mod: ModInfo) -> None:
        worker = StaleCheckWorker([mod], self)
        worker.checked.connect(self._on_stale_checked)
        self._misc_workers.append(worker)
        worker.finished.connect(
            lambda: setattr(self, "_misc_workers", [w for w in self._misc_workers if w.isRunning()])
        )
        worker.start()
        InfoBar.info(
            title=tr("mods.ctx_checking", "Проверяю «{n}»…", n=mod.name),
            content="",
            parent=self.window(),
            duration=3000,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _remove_from_list(self, mods: ModInfo | list[ModInfo]) -> None:
        if not self.settings:
            return
        if isinstance(mods, ModInfo):
            mods = [mods]
        if not mods:
            return
        for mod in mods:
            key = mod.folder_name.lower()
            if key not in self.settings.excluded_mods:
                self.settings.excluded_mods.append(key)
        self.settings.save()
        self.refresh()
        title = (
            tr("mods.ctx_removed", "«{n}» убран из списка", n=mods[0].name)
            if len(mods) == 1
            else tr("mods.ctx_removed_bulk", "Убрано из списка: {n}", n=len(mods))
        )
        InfoBar.success(
            title=title, content="", parent=self.window(), duration=3000, position=InfoBarPosition.TOP_RIGHT
        )

    def _open_hidden_mods(self) -> None:
        if not self.settings or not self.registry:
            return
        dlg = HiddenModsDialog(list(self.settings.excluded_mods), self.registry.hidden, self)
        if not dlg.exec():
            return
        restore = dlg.selected_keys()
        if not restore:
            return
        self.settings.excluded_mods = [k for k in self.settings.excluded_mods if k not in restore]
        self.settings.save()
        self.refresh()

    def _open_flags(self) -> None:
        if not self.registry:
            return
        dlg = ModFlagsDialog(self.registry, self)
        dlg.exec()
        if dlg.changed:
            self._rebuild()

    # ---------------------------------------------------------------- ребилд

    def _rebuild_mod(self, mod: ModInfo, item: QTreeWidgetItem | None = None) -> None:
        if not self.settings or not mod.sources:
            return
        # Запущенная игра держит PBO открытыми — запаковка не сможет их
        # перезаписать. Проверяем в момент клика, а не блокируем кнопку:
        # процессы могут стартовать и завершиться между перерисовками списка.
        if dayz_running():
            InfoBar.warning(
                title=tr("mods.rebuild_busy", "Нельзя пересобрать при запущенной игре"),
                content=tr("mods.rebuild_busy_body", "Остановите сервер и клиент: они держат PBO открытыми."),
                parent=self.window(),
                duration=6000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        if item is not None:
            # заменяем кнопку крутящимся индикатором — видно, что идёт сборка;
            # после завершения self.refresh() пересоздаст строку с обычной кнопкой
            spinner = IndeterminateProgressRing()
            spinner.setFixedSize(self._REBUILD_CELL_SIZE, self._REBUILD_CELL_SIZE)
            spinner.setStrokeWidth(3)
            self.tree.setItemWidget(item, COL_REBUILD, spinner)
        InfoBar.info(
            title=tr("mods.rebuild_started", "Пересборка «{n}»…", n=mod.name),
            content="",
            parent=self.window(),
            duration=3000,
            position=InfoBarPosition.TOP_RIGHT,
        )
        if self.log_cb:
            self.log_cb(tr("mods.rebuild_log_start", "Пакуем мод «{n}»", n=mod.name))
        names = [packer.pbo_for_source(mod, s).name for s in mod.sources]
        if self.pack_table is not None:
            self.pack_table.start(names)
        if self.packed_cb is not None:
            self.packed_cb(names)
        worker = RebuildWorker(self.settings, mod, list(mod.sources), self)
        worker.source_start.connect(self._on_pack_source_start)
        worker.source_done.connect(self._on_pack_source_done)
        worker.done.connect(lambda ok, msg, m=mod: self._rebuild_done(ok, msg, m))
        self._rebuild_workers.append(worker)
        worker.start()

    def _on_pack_source_start(self, name: str) -> None:
        if self.pack_table is not None:
            self.pack_table.set_status(name, packing_log.PACKING)

    def _on_pack_source_done(self, name: str, ok: bool, ms: int, w: int, e: int) -> None:
        if self.pack_table is not None:
            self.pack_table.set_status(name, packing_log.OK if ok else packing_log.FAIL, ms, w, e)

    def _rebuild_done(self, ok: bool, msg: str, mod: ModInfo) -> None:
        if ok:
            InfoBar.success(
                title=tr("mods.rebuild_ok", "«{n}» пересобран", n=mod.name),
                content="",
                parent=self.window(),
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            if self.log_cb:
                self.log_cb(tr("mods.rebuild_log_ok", "Запаковка мода «{n}» завершена", n=mod.name))
        else:
            InfoBar.error(
                title=tr("mods.rebuild_failed", "Ошибка пересборки «{n}»", n=mod.name),
                content=msg,
                parent=self.window(),
                duration=8000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            if self.log_cb:
                if msg:
                    self.log_cb(msg, "error")
                self.log_cb(tr("mods.rebuild_log_failed", "Ошибка пересборки «{n}».", n=mod.name), "error")
        if self.log_cb:
            self.log_cb("=================")
        self._rebuild_workers = [w for w in self._rebuild_workers if w.isRunning()]
        self.refresh()

    def _add_folder(self) -> None:
        if not self.settings:
            return
        picked = QFileDialog.getExistingDirectory(self, tr("mods.add_dir_pick", "Папка с модами или @папка мода"))
        if not picked:
            return
        p = Path(picked)
        candidates = (
            [p] if p.name.startswith("@") else [c for c in p.iterdir() if c.is_dir() and c.name.startswith("@")]
        )
        if not candidates:
            InfoBar.warning(
                title=tr("mods.add_none", "В папке нет @модов — нечего добавлять."),
                content="",
                parent=self,
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        # невалидные моды не блокируют добавление папки — показываем их
        # в дереве красным и с заблокированной галкой, а не прячем
        problems = [err for c in candidates if (err := validate_mod_dir(c))]
        valid = len(candidates) - len(problems)
        if str(p) not in self.settings.local_mods_dirs:
            self.settings.local_mods_dirs.append(str(p))
            self.settings.save()
        self.refresh()
        InfoBar.success(
            title=tr(
                "mods.add_ok_dir", "Папка добавлена. Валидных модов: {v}, с проблемами: {p}", v=valid, p=len(problems)
            ),
            content="\n".join(problems[:6]),
            parent=self,
            duration=5000,
            position=InfoBarPosition.TOP_RIGHT,
        )
