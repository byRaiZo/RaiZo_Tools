"""Окно «Подключить моды» — выбор и клиент/сервер модов для конкретного
пресета сервера. Общие настройки модов (сорсы, зависимости, признак
«Серверный», свои флаги) задаются отдельно на вкладке «Моды»."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidgetItem,
    QHeaderView,
    QInputDialog,
    QScrollArea,
    QWidget,
)
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    TreeWidget,
    ComboBox,
    SearchLineEdit,
    CaptionLabel,
    BodyLabel,
    HyperlinkLabel,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
)

from core import deps, steam_api, steam_urls
from core.i18n import tr
from core.mods import sort_key as mods_sort_key, ModRegistry, ModInfo, SOURCE_STEAM, load_flag_defs
from core.presets import ServerPreset, ModPreset
from core.settings import Settings
from ui.mods_panel import (
    DependencyResolveWorker,
    DependencyDialog,
    SetsDialog,
)
from ui.mod_flags_dialog import flag_icon, _swatch_icon
from ui.steam_watch import SteamWatcher
from ui.theme import ThemedDialog

_GREY = QColor("#888888")
_GREEN = QColor("#2e7d32")

(COL_NAME, COL_TYPE) = range(2)
_KEYED_COLS = (COL_NAME,)


class _SortableItem(QTreeWidgetItem):
    """Сортирует COL_NAME по значению из UserRole+1, а не по тексту (своя копия
    mods_panel.ModTreeItem — та завязана на индексы колонок вкладки «Моды»,
    здесь у диалога другой набор колонок)."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        col = tree.sortColumn() if tree else 0
        if col in _KEYED_COLS:
            a = self.data(col, Qt.ItemDataRole.UserRole + 1)
            b = other.data(col, Qt.ItemDataRole.UserRole + 1)
            if a is not None and b is not None:
                return a < b
        return self.text(col).lower() < other.text(col).lower()


class CollectionFetchWorker(QThread):
    """Загрузка списка модов коллекции Steam Workshop (в фоне, не блокирует UI)."""

    done = Signal(list, dict, str)  # id модов по порядку, {id: название}, текст ошибки

    def __init__(self, collection_id: str, parent=None):
        super().__init__(parent)
        self.collection_id = collection_id

    def run(self) -> None:
        try:
            children = steam_api.get_collection_children(self.collection_id)
        except Exception as e:  # noqa: BLE001 — сеть/битая ссылка — показываем как ошибку
            self.done.emit([], {}, str(e))
            return
        if not children:
            self.done.emit([], {}, tr("collection.empty", "Коллекция не найдена или пуста."))
            return
        try:
            names = steam_api.get_published_file_names(children)
        except Exception:  # noqa: BLE001 — названия не критичны, покажем голые id
            names = {}
        self.done.emit(children, names, "")


class CollectionDialog(ThemedDialog):
    """Список модов коллекции — присутствующие обычным текстом, отсутствующие
    серым с ссылкой на страницу в Steam."""

    def __init__(self, child_ids: list[str], names: dict[str, str], registry: ModRegistry, parent=None):
        super().__init__(parent)
        self.found_mods: list[ModInfo] = []
        missing_ids = []

        self.setWindowTitle(tr("collection.title", "Коллекция Steam"))
        self.resize(480, 440)
        layout = QVBoxLayout(self)

        found_by_id = {m.workshop_id: m for m in registry.all() if m.source == SOURCE_STEAM and m.workshop_id}
        # присутствующие — сверху, отсутствующие — снизу; порядок внутри
        # каждой группы — как в самой коллекции (стабильная сортировка)
        ordered = sorted(child_ids, key=lambda wid: 0 if wid in found_by_id else 1)
        for wid in ordered:
            if wid in found_by_id:
                self.found_mods.append(found_by_id[wid])
            else:
                missing_ids.append(wid)

        hint = CaptionLabel(
            tr(
                "collection.missing_msg",
                "Не хватает модов: {n} из {total}. Подпишитесь на них в Steam, обновите список "
                "модов и повторите подключение коллекции — либо подключите то, что уже есть.",
                n=len(missing_ids),
                total=len(child_ids),
            )
            if missing_ids
            else tr("collection.all_present", "Все моды коллекции уже есть в реестре.")
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # список — в прокручиваемой области с ограниченной высотой: коллекция
        # может быть большой, и без этого окно раздувалось бы под все строки,
        # не помещаясь на экран
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # без этого viewport остаётся системным белым в тёмной теме
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        inner = QWidget()
        inner.setObjectName("collectionList")
        inner.setStyleSheet("QWidget#collectionList{background:transparent;}")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        # виджеты недостающих модов — их состояние обновляет наблюдатель Steam
        self._missing_rows: dict[str, tuple[BodyLabel, BodyLabel, HyperlinkLabel]] = {}
        for wid in ordered:
            found = found_by_id.get(wid)
            row = QHBoxLayout()
            if found:
                row.addWidget(BodyLabel(found.name), 1)
                status = BodyLabel(tr("collection.installed", "Установлен"))
                status.setStyleSheet(f"color: {_GREEN.name()};")
                row.addWidget(status)
            else:
                lbl = BodyLabel(names.get(wid) or wid)
                lbl.setStyleSheet(f"color: {_GREY.name()};")
                row.addWidget(lbl, 1)
                status = BodyLabel("")
                status.hide()
                row.addWidget(status)
                link = HyperlinkLabel(parent=self)
                link.setUrl(QUrl(steam_urls.workshop_item(wid)))
                link.setText(tr("mods.deps_open_workshop", "Открыть в Workshop"))
                row.addWidget(link)
                self._missing_rows[wid] = (lbl, status, link)
            inner_layout.addLayout(row)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        # Подписка происходит в Steam, окно об этом само не узнает — поэтому
        # следим за воркшопом и отмечаем моды скачавшимися прямо в списке.
        self.watcher = SteamWatcher(self)
        self.watcher.watch_workshop(steam_urls.APP_DAYZ)
        self.watcher.workshop_changed.connect(self._workshop_changed)
        if self._missing_rows:
            self.watcher.start()

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        if self.found_mods:
            b_connect = PrimaryPushButton(
                FIF.LINK, tr("collection.connect_present", "Подключить имеющиеся ({n})", n=len(self.found_mods))
            )
            b_connect.clicked.connect(self.accept)
            btns.addWidget(b_connect)
        layout.addLayout(btns)

    def _workshop_changed(self, ws) -> None:
        """Отмечает в списке моды, которые Steam качает или уже скачал.

        Строка мода остаётся на месте: перестраивать список под пользователем,
        пока он его читает, неудобнее, чем поменять подпись справа.
        """
        for wid, (lbl, status, link) in self._missing_rows.items():
            if wid in ws.installed:
                lbl.setStyleSheet("")
                status.setText(tr("collection.installed", "Установлен"))
                status.setStyleSheet(f"color: {_GREEN.name()};")
                status.show()
                link.hide()
            elif wid in ws.downloading:
                status.setText(tr("collection.downloading", "Скачивается…"))
                status.setStyleSheet(f"color: {_GREY.name()};")
                status.show()
            else:
                status.hide()


class ConnectModsDialog(ThemedDialog):
    """Модальное окно выбора модов пресета — открывается кнопкой «Подключить
    моды» с главной страницы."""

    def __init__(self, registry: ModRegistry, preset: ServerPreset, settings: Settings, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.preset = preset
        self.settings = settings
        self._building = False
        self._dep_workers: list[DependencyResolveWorker] = []
        self._collection_worker: CollectionFetchWorker | None = None

        self.setWindowTitle(tr("connect.title", "Подключить моды — {n}", n=preset.name))
        self.resize(620, 640)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        b_all = PushButton(tr("mods.enable_all", "Включить все"))
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none = PushButton(tr("mods.disable_all", "Выключить все"))
        b_none.clicked.connect(lambda: self._set_all(False))
        for b in (b_all, b_none):
            top.addWidget(b)
        top.addStretch(1)
        layout.addLayout(top)

        sets_row = QHBoxLayout()
        b_save_set = PushButton(FIF.SAVE_AS, tr("mods.save_set", "Сохранить как набор…"))
        b_save_set.clicked.connect(self._save_set)
        # шеврон вместо галки — намекает, что кнопка открывает выбор из списка,
        # а не сразу «подтверждает» что-то
        b_apply_set = PushButton(FIF.CHEVRON_DOWN_MED, tr("mods.apply_set", "Выбрать набор"))
        b_apply_set.clicked.connect(self._apply_set_menu)
        b_collection = PushButton(FIF.CLOUD_DOWNLOAD, tr("collection.connect_btn", "Подключить коллекцию…"))
        b_collection.clicked.connect(self._connect_collection)
        sets_row.addWidget(b_save_set)
        sets_row.addWidget(b_apply_set)
        sets_row.addWidget(b_collection)
        sets_row.addStretch(1)
        layout.addLayout(sets_row)

        filter_row = QHBoxLayout()
        self.search = SearchLineEdit()
        self.search.setPlaceholderText(tr("mods.search_ph", "Фильтр по названию…"))
        self.search.textChanged.connect(lambda _t: self._apply_filter())
        filter_row.addWidget(self.search, 1)
        self.tag_combo = ComboBox()
        self.tag_combo.addItem(tr("connect.tag_all", "Все теги"), userData="")
        for d in load_flag_defs():
            icon = flag_icon(d) or _swatch_icon(d.color)
            self.tag_combo.addItem(d.name, icon=icon, userData=d.id)
        self.tag_combo.currentIndexChanged.connect(lambda _i: self._apply_filter())
        filter_row.addWidget(self.tag_combo)
        layout.addLayout(filter_row)

        self.tree = TreeWidget(self)
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(
            [
                tr("mods.col_name", "Мод"),
                tr("connect.col_type", "Тип"),
            ]
        )
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.setSortIndicator(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree, 1)

        hint = CaptionLabel(
            tr(
                "connect.hint",
                "Галка подключает мод. «Тип» — Клиент/Сервер задаётся на вкладке «Моды» "
                "(признак «Серверный»); мод автоматически уходит в -mod или -serverMod "
                "согласно этому признаку. Клик по заголовку колонки сортирует по ней.",
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_close = PrimaryPushButton(tr("common.close", "Закрыть"))
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_close)
        layout.addLayout(btns)

        self._rebuild()

        # Пользователь мог подписаться на мод в Steam, не закрывая это окно —
        # ловим появление новых модов и обновляем список сами, чтобы не
        # приходилось идти на вкладку «Моды» и жать «Обновить».
        self._known_workshop: set[str] | None = None
        self.watcher = SteamWatcher(self)
        self.watcher.watch_workshop(steam_urls.APP_DAYZ)
        self.watcher.workshop_changed.connect(self._workshop_changed)
        self.watcher.start()

    def _workshop_changed(self, ws) -> None:
        installed = set(ws.installed)
        if self._known_workshop is None:
            self._known_workshop = installed  # первый снимок — точка отсчёта
            return
        fresh = installed - self._known_workshop
        self._known_workshop = installed
        if not fresh:
            return

        self.registry.scan()
        self._rebuild()
        names = [m.name for m in self.registry.all() if m.source == SOURCE_STEAM and m.workshop_id in fresh]
        InfoBar.success(
            title=tr("connect.new_mods", "Скачано новых модов: {n}", n=len(fresh)),
            content=", ".join(names) or ", ".join(sorted(fresh)),
            parent=self,
            duration=6000,
            position=InfoBarPosition.TOP_RIGHT,
        )

    # ---------------------------------------------------------------- дерево

    def _rebuild(self) -> None:
        hdr = self.tree.header()
        sort_col = hdr.sortIndicatorSection()
        sort_order = hdr.sortIndicatorOrder()
        self._building = True
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        flag_defs = {d.id: d for d in load_flag_defs()}
        for mod in self.registry.all():
            if not mod.valid:
                continue
            item = self._make_item(mod, flag_defs)
            self.tree.addTopLevelItem(item)
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(sort_col, sort_order)
        self._building = False
        self._apply_filter()

    def _make_item(self, mod: ModInfo, flag_defs: dict) -> _SortableItem:
        p = self.preset
        enabled = (
            self.registry.index_of(mod, p.mods) is not None or self.registry.index_of(mod, p.server_mods) is not None
        )

        type_text = tr("connect.type_server", "Сервер") if mod.is_server else tr("connect.type_client", "Клиент")
        item = _SortableItem([mod.name, type_text])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(COL_NAME, Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        # ключ сортировки: подключённые впереди, дальше — общий порядок
        # (группы по флагам, потом всё остальное по алфавиту)
        item.setData(COL_NAME, Qt.ItemDataRole.UserRole + 1, (0 if enabled else 1,) + mods_sort_key(mod))
        item.setData(COL_NAME, Qt.ItemDataRole.UserRole, mod.folder_name.lower())
        flag_ids = [fid for fid in mod.flags if fid in flag_defs]
        if flag_ids:
            defs = [flag_defs[fid] for fid in flag_ids]
            font = item.font(COL_NAME)
            font.setBold(any(d.bold for d in defs))
            font.setItalic(any(d.italic for d in defs))
            font.setUnderline(any(d.underline for d in defs))
            item.setFont(COL_NAME, font)
            item.setForeground(COL_NAME, QColor(defs[0].color))
            icon = flag_icon(defs[0])
            if icon:
                item.setIcon(COL_NAME, icon)
            item.setToolTip(COL_NAME, tr("mods.flags_tip", "Флаги: {f}", f=", ".join(d.name for d in defs)))
        item.setToolTip(
            COL_TYPE, tr("connect.type_tip", "Клиент/Сервер задаётся признаком «Серверный» на вкладке «Моды».")
        )
        return item

    def _iter_items(self):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item is not None:
                yield item

    def _item_mod(self, item: QTreeWidgetItem) -> ModInfo | None:
        key = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        return self.registry.mods.get(key) if key else None

    def _apply_filter(self) -> None:
        q = self.search.text().strip().lower()
        tag = self.tag_combo.currentData()
        for item in self._iter_items():
            visible = not q or q in item.text(COL_NAME).lower()
            if visible and tag:
                mod = self._item_mod(item)
                visible = bool(mod) and tag in mod.flags
            item.setHidden(not visible)

    # ---------------------------------------------------------------- изменения

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._building or column != COL_NAME:
            return
        mod = self._item_mod(item)
        if not mod:
            return
        p = self.preset
        was_enabled = (
            self.registry.index_of(mod, p.mods) is not None or self.registry.index_of(mod, p.server_mods) is not None
        )
        enabled = item.checkState(COL_NAME) == Qt.CheckState.Checked

        def drop(name_list):
            i = self.registry.index_of(mod, name_list)
            if i is not None:
                name_list.pop(i)

        drop(p.mods)
        drop(p.server_mods)
        if enabled:
            (p.server_mods if mod.is_server else p.mods).append(mod.name)
        p.save()
        if enabled and not was_enabled:
            self._check_dependencies([mod])

    def _set_all(self, state: bool) -> None:
        p = self.preset
        if not state:
            p.mods, p.server_mods = [], []
        else:
            for item in self._iter_items():
                mod = self._item_mod(item)
                if (
                    mod
                    and self.registry.index_of(mod, p.mods) is None
                    and self.registry.index_of(mod, p.server_mods) is None
                ):
                    (p.server_mods if mod.is_server else p.mods).append(mod.name)
        p.save()
        self._rebuild()

    # ---------------------------------------------------------------- зависимости

    def _check_dependencies(self, mods: list[ModInfo]) -> None:
        """Запускает обход графа зависимостей для только что подключённых модов.

        Обход общий для Steam и локальных модов и идёт вглубь: подключение мода
        В, который зависит от А, а тот от Б, покажет и А, и Б сразу.
        """
        if not self.settings or not mods:
            return
        worker = DependencyResolveWorker(mods, self.registry, self.settings.steam_api_key, self)
        worker.done.connect(lambda res, roots=mods: self._on_dependencies_resolved(roots, res))
        self._dep_workers.append(worker)
        worker.start()

    def _on_dependencies_resolved(self, roots: list[ModInfo], res) -> None:
        self._dep_workers = [w for w in self._dep_workers if w.isRunning()]
        res = deps.filter_connected(res, self.registry, self.preset.mods, self.preset.server_mods)
        if res.empty:
            return  # всё нужное уже подключено — беспокоить незачем
        dlg = DependencyDialog(roots, res, self)
        if not dlg.exec():
            return
        self._connect_selected(dlg.selected_mods())

    def _connect_selected(self, dep_mods: list[ModInfo]) -> None:
        """Подключает выбранные зависимости.

        Повторный обход не запускаем: resolve() уже вернул всю цепочку целиком,
        так что новых зависимостей у них быть не может.
        """
        added = 0
        for dep_mod in dep_mods:
            if (
                self.registry.index_of(dep_mod, self.preset.mods) is None
                and self.registry.index_of(dep_mod, self.preset.server_mods) is None
            ):
                (self.preset.server_mods if dep_mod.is_server else self.preset.mods).append(dep_mod.name)
                added += 1
        if added:
            self.preset.save()
            self._rebuild()
            InfoBar.success(
                title=tr("mods.deps_added", "Подключено зависимостей: {n}", n=added),
                content="",
                parent=self,
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
            )

    # ---------------------------------------------------------------- наборы

    def _save_set(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("mods.set_title", "Набор модов"), tr("mods.set_name", "Название набора:")
        )
        if not ok or not name.strip():
            return
        ModPreset(name=name.strip(), mods=list(self.preset.mods), server_mods=list(self.preset.server_mods)).save()
        InfoBar.success(
            title=tr("mods.set_saved", "Набор «{n}» сохранён.", n=name.strip()),
            content="",
            parent=self,
            duration=3000,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _apply_set_menu(self) -> None:
        sets = ModPreset.load_all()
        if not sets:
            InfoBar.info(
                title=tr("mods.no_sets", "Сохранённых наборов пока нет."),
                content="",
                parent=self,
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        dlg = SetsDialog(sets, self)
        if not dlg.exec():
            return
        chosen = dlg.selected()
        if not chosen:
            return
        self._apply_sets(chosen)

    def _apply_sets(self, chosen: list[ModPreset]) -> None:
        """Объединяет моды выбранных наборов (без дублей, первое вхождение решает
        серверный/обычный) и заменяет ими текущий список подключённых модов."""
        mods: list[str] = []
        server_mods: list[str] = []
        seen: set[str] = set()
        for mp in chosen:
            for n in mp.mods:
                if n.lower() not in seen:
                    seen.add(n.lower())
                    mods.append(n)
            for n in mp.server_mods:
                if n.lower() not in seen:
                    seen.add(n.lower())
                    server_mods.append(n)
        self.preset.mods = mods
        self.preset.server_mods = server_mods
        self.preset.save()
        self._rebuild()
        # набор мог быть сохранён без зависимостей — проверяем то, что подключилось
        self._check_dependencies([m for m in (self.registry.get(n) for n in mods + server_mods) if m])

    # ---------------------------------------------------------------- коллекция

    def _connect_collection(self) -> None:
        text, ok = QInputDialog.getText(
            self,
            tr("collection.connect_btn", "Подключить коллекцию…"),
            tr("collection.url_prompt", "Ссылка на коллекцию Steam Workshop (или её id):"),
        )
        if not ok or not text.strip():
            return
        collection_id = steam_api.parse_collection_id(text)
        if not collection_id:
            InfoBar.error(
                title=tr("collection.bad_url", "Не удалось распознать ссылку на коллекцию."),
                content="",
                parent=self,
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        if self._collection_worker and self._collection_worker.isRunning():
            return
        InfoBar.info(
            title=tr("collection.fetching", "Загружаю список модов коллекции…"),
            content="",
            parent=self,
            duration=3000,
            position=InfoBarPosition.TOP_RIGHT,
        )
        self._collection_worker = CollectionFetchWorker(collection_id, self)
        self._collection_worker.done.connect(self._on_collection_fetched)
        self._collection_worker.start()

    def _on_collection_fetched(self, child_ids: list[str], names: dict[str, str], error: str) -> None:
        if error:
            InfoBar.error(
                title=tr("collection.error", "Не удалось загрузить коллекцию"),
                content=error,
                parent=self,
                duration=6000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return

        missing = [
            wid
            for wid in child_ids
            if not any(m.source == SOURCE_STEAM and m.workshop_id == wid for m in self.registry.all())
        ]
        if not missing:
            found = [m for m in self.registry.all() if m.source == SOURCE_STEAM and m.workshop_id in child_ids]
            self._connect_mods(found)
            InfoBar.success(
                title=tr("collection.connected", "Коллекция подключена: {n} модов", n=len(found)),
                content="",
                parent=self,
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return

        dlg = CollectionDialog(child_ids, names, self.registry, self)
        if dlg.exec():
            self._connect_mods(dlg.found_mods)

    def _connect_mods(self, mods: list[ModInfo]) -> None:
        """Подключает моды в конец списка (клиент/сервер — по mod.is_server),
        пропуская уже подключённые."""
        added = 0
        for mod in mods:
            if (
                self.registry.index_of(mod, self.preset.mods) is None
                and self.registry.index_of(mod, self.preset.server_mods) is None
            ):
                (self.preset.server_mods if mod.is_server else self.preset.mods).append(mod.name)
                added += 1
        if added:
            self.preset.save()
            self._rebuild()
            # у модов коллекции могут быть зависимости вне её состава
            self._check_dependencies(mods)
