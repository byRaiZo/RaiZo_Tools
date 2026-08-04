"""Выбор существующей миссии или установка новой из каталога."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    ComboBox,
    ToolButton,
    PushButton,
    PrimaryPushButton,
    CheckBox,
    BodyLabel,
    CaptionLabel,
    HyperlinkLabel,
    IndeterminateProgressBar,
    FluentIcon as FIF,
)

from core import missions, steam_urls
from core.downloader import MissionCopyWorker
from core.i18n import tr
from core.missions import CatalogEntry
from core.settings import Settings
from ui.download_window import DownloadWindow
from ui.theme import ThemedDialog

_WARN_COLOR = "#e08f00"


class CopyDialog(ThemedDialog):
    """Модальное окошко локального копирования шаблона в миссию пресета."""

    def __init__(self, src, dst, replace: bool = False, keep_storage: bool = True, parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle(tr("mission.copy_title", "Создание миссии"))
        self.resize(440, 130)
        layout = QVBoxLayout(self)
        self.status = BodyLabel(tr("mission.copying", "Копирование {s} → {d}…", s=src.name, d=dst.name))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = IndeterminateProgressBar()
        self.bar.start()
        layout.addWidget(self.bar)
        self.btn = PushButton(tr("dl.close", "Закрыть"))
        self.btn.setEnabled(False)
        self.btn.clicked.connect(self.close)
        layout.addWidget(self.btn)

        self.worker = MissionCopyWorker(src, dst, replace=replace, keep_storage=keep_storage)
        self.worker.done.connect(self._done)
        self.worker.start()

    def _done(self, ok: bool, result: str) -> None:
        self.bar.stop()
        if ok:
            self.status.setText(tr("mission.copied", "Готово: {p}", p=result))
        else:
            self.status.setText(result)
        self.btn.setEnabled(True)


_LEGACY = "legacy"
_INSTALLED = "installed"
_CATALOG = "cat"


class UpdateMissionDialog(ThemedDialog):
    """Подтверждение пересоздания миссии из шаблона + вопрос про storage."""

    def __init__(self, mission_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mission.recreate_title", "Пересоздание миссии"))
        self.resize(480, 170)
        layout = QVBoxLayout(self)
        warn = BodyLabel(
            tr(
                "mission.recreate_warn",
                "«{n}» будет пересоздана из шаблона actual.<карта>.\nВаши правки файлов миссии будут потеряны.",
                n=mission_name,
            )
        )
        warn.setWordWrap(True)
        layout.addWidget(warn)
        self.keep_storage = CheckBox(tr("mission.keep_storage", "Сохранить storage_* (персистентность, персонажи)"))
        self.keep_storage.setChecked(False)
        layout.addWidget(self.keep_storage)
        layout.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(FIF.COPY, tr("mission.recreate", "Пересоздать"))
        b_ok.clicked.connect(self.accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        layout.addLayout(btns)


class MapPicker(QWidget):
    """Комбо установленных миссий и доступных загрузок из каталога."""

    changed = Signal()  # смена карты/имени — редакторы обновляют подсказки

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings: Settings | None = None
        self.branch = "stable"
        self.mode = "diag"
        self.preset_name = ""
        self._windows: list[QWidget] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        row = QHBoxLayout()
        self.combo = ComboBox()
        self.combo.currentIndexChanged.connect(lambda _i: self._update_status())
        self.b_upd = ToolButton(FIF.SYNC)
        self.b_upd.setToolTip(tr("mission.upd_tip", "Обновить миссию напрямую с GitHub"))
        self.b_upd.clicked.connect(self._update_template)
        self.b_recreate = ToolButton(FIF.COPY)
        self.b_recreate.setToolTip(tr("mission.recreate_tip", "Пересоздать миссию пресета из шаблона"))
        self.b_recreate.clicked.connect(self._recreate_mission)
        self.b_recreate.hide()
        row.addWidget(self.combo, 1)
        row.addWidget(self.b_upd)
        row.addWidget(self.b_recreate)
        col.addLayout(row)
        self.status = CaptionLabel("")
        col.addWidget(self.status)
        warn_row = QHBoxLayout()
        self.map_warn = CaptionLabel("")
        self.map_warn.setStyleSheet(f"color: {_WARN_COLOR};")
        self.map_warn.setWordWrap(True)
        self.map_link = HyperlinkLabel(parent=self)
        self.map_link.setText(tr("mission.map_open_workshop", "Открыть в Workshop"))
        self.map_link.hide()
        warn_row.addWidget(self.map_warn, 1)
        warn_row.addWidget(self.map_link)
        col.addLayout(warn_row)

    # ------------------------------------------------------------------

    def set_context(
        self, settings: Settings, branch: str, mode: str, preset_name: str, current_mission: str = ""
    ) -> None:
        self.settings = settings
        self.branch = branch
        self.mode = mode
        self.preset_name = preset_name
        self.combo.blockSignals(True)
        self.combo.clear()
        select = 0
        installed: list[str] = []
        base = self._missions_base()
        if base and base.is_dir():
            installed = sorted(
                (path.name for path in base.iterdir() if path.is_dir()),
                key=str.casefold,
            )

        # Абсолютный/старый путь за пределами mpmissions сохраняем как есть.
        if current_mission and current_mission not in installed:
            derived_names = {f"{preset_name}.{e.world}" for e in missions.load_catalog()}
            if current_mission not in derived_names:
                self.combo.addItem(
                    tr("mission.keep_current", "Текущая миссия: {m}", m=current_mission),
                    userData=(_LEGACY, current_mission),
                )
                select = self.combo.count() - 1

        for mission_name in installed:
            self.combo.addItem(
                tr("mission.use_installed", "Использовать: {m}", m=mission_name),
                userData=(_INSTALLED, mission_name),
            )
            if mission_name == current_mission:
                select = self.combo.count() - 1

        for entry in missions.load_catalog():
            self.combo.addItem(
                tr("mission.download_new", "Скачать новую: {n}  (.{w})", n=entry.title, w=entry.world),
                userData=(_CATALOG, entry),
            )
            if current_mission not in installed and current_mission == f"{preset_name}.{entry.world}":
                select = self.combo.count() - 1

        if self.combo.count() == 0 and current_mission:
            self.combo.addItem(
                tr("mission.keep_current", "Текущая миссия: {m}", m=current_mission),
                userData=(_LEGACY, current_mission),
            )
        self.combo.setCurrentIndex(select)
        self.combo.blockSignals(False)
        self._update_status()

    def set_preset_name(self, name: str) -> None:
        self.preset_name = name
        self._update_status()

    # ------------------------------------------------------------------

    def _data(self) -> tuple[str | None, str | CatalogEntry | None]:
        return self.combo.currentData() or (None, None)

    def mission_name(self) -> str:
        kind, val = self._data()
        if kind in (_LEGACY, _INSTALLED) and isinstance(val, str):
            return val
        if kind == _CATALOG and self.preset_name and isinstance(val, CatalogEntry):
            return f"{self.preset_name}.{val.world}"
        return ""

    def world(self) -> str:
        """Имя мира выбранной карты (для схемы имён <пресет>_<карта>)."""
        kind, val = self._data()
        if kind == _CATALOG and isinstance(val, CatalogEntry):
            return val.world
        if kind in (_LEGACY, _INSTALLED) and isinstance(val, str) and "." in val:
            return val.rsplit(".", 1)[1]
        return ""

    def catalog_entry(self) -> CatalogEntry | None:
        kind, val = self._data()
        if kind == _CATALOG and isinstance(val, CatalogEntry):
            return val
        world = self.world()
        return next((entry for entry in missions.load_catalog() if entry.world == world), None)

    def _missions_base(self):
        if not self.settings:
            return None
        base = missions.mpmissions_dir(self.settings, self.branch, self.mode)
        return base if str(base) else None

    def _mission_dir(self):
        base = self._missions_base()
        name = self.mission_name()
        return (base / name) if (base and name) else None

    def _template_dir(self):
        return None

    def _update_status(self) -> None:
        kind, _val = self._data()
        d = self._mission_dir()
        installed = bool(d and d.is_dir())
        if kind in (_LEGACY, _INSTALLED):
            self.status.setText(
                tr(
                    "mission.st_existing",
                    "Используется существующая папка без копирования.",
                )
            )
            self.b_upd.setEnabled(False)
            self.b_recreate.setEnabled(False)
            self._update_map_warning(self.catalog_entry())
            self.changed.emit()
            return
        entry = self.catalog_entry()
        if not self.preset_name:
            self.status.setText("")
        elif installed and d is not None:
            self.status.setText(tr("mission.st_ok", "✓ {n} — установлена", n=d.name))
        else:
            self.status.setText(
                "Миссия {n} будет установлена напрямую с github.com/{repo}".format(
                    n=d.name if d else "?",
                    repo=entry.repo if entry else "?",
                )
            )
        self.b_upd.setEnabled(installed and bool(entry))
        self.b_recreate.setEnabled(False)
        self._update_map_warning(entry)
        self.changed.emit()

    def _update_map_warning(self, entry: CatalogEntry | None) -> None:
        """Мод карты (не bundled в репозиторий миссии, отдельная подписка в
        Steam Workshop) — предупреждаем, если его нет, ссылка на страницу."""
        workshop_id = entry.map_mod if entry else ""
        if not workshop_id or not self.settings or missions.map_mod_installed(self.settings, workshop_id):
            self.map_warn.setText("")
            self.map_link.hide()
            return
        self.map_warn.setText(tr("mission.map_missing", "Не найден мод карты — без него миссия не запустится."))
        self.map_link.setUrl(QUrl(steam_urls.workshop_item(workshop_id)))
        self.map_link.show()

    # ------------------------------------------------------------------

    def _mods_dl_dir(self):
        from core.layout import mods_dl_dir

        return mods_dl_dir(self.settings) if self.settings else None

    def ensure_mission(self) -> None:
        """Устанавливает отсутствующую миссию сразу в DayZServer/mpmissions."""
        kind, _val = self._data()
        if kind != _CATALOG:
            return
        entry = self.catalog_entry()
        d = self._mission_dir()
        if not entry or not d or d.is_dir():
            return
        win = DownloadWindow(entry, d.parent, d.name, mods_dir=self._mods_dl_dir())
        win.finished_ok.connect(lambda _p: self._update_status())
        win.show()
        self._windows.append(win)  # держим ссылку, иначе окно соберёт GC

    def _start_copy(self, src, dst, replace: bool = False, keep_storage: bool = True) -> None:
        dlg = CopyDialog(src, dst, replace=replace, keep_storage=keep_storage, parent=self.window())
        dlg.worker.done.connect(lambda _ok, _p: self._update_status())
        dlg.show()
        self._windows.append(dlg)

    def _update_template(self) -> None:
        kind, _val = self._data()
        if kind != _CATALOG:
            return
        d = self._mission_dir()
        entry = self.catalog_entry()
        if not d or not entry:
            return
        win = DownloadWindow(entry, d.parent, d.name, replace=True, keep_storage=True, mods_dir=self._mods_dl_dir())
        win.finished_ok.connect(lambda _p: self._update_status())
        win.show()
        self._windows.append(win)

    def _recreate_mission(self) -> None:
        self._update_template()
