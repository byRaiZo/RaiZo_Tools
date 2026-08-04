"""Создание пресетов — «Ленивый» мастер; «Расширенный» редактор — для правки уже созданных."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QFileDialog,
    QFrame,
    QGroupBox,
    QScrollArea,
    QWizardPage,
    QWidget,
)
from qfluentwidgets import (
    LineEdit,
    ComboBox,
    CheckBox,
    SpinBox,
    PushButton,
    PrimaryPushButton,
    ToolButton,
    RadioButton,
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
)

from core.i18n import tr
from core.params import default_params, specs_for, FLAG, SWITCH, INT, SERVER, CLIENT
from core.presets import ServerPreset, MODE_DIAG, MODE_DEDICATED
from core.settings import Settings, STABLE, EXPERIMENTAL
from ui.mission_picker import MapPicker
from ui.theme import ThemedDialog, ThemedWizard


class _NoWheelSpinBox(SpinBox):
    """Числовое поле, не перехватывающее прокрутку родительского окна."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class _PathField(QHBoxLayout):
    def __init__(self, parent: QWidget, value: str, pick_dir: bool, root_hint: str = ""):
        super().__init__()
        self.parent_widget = parent
        self.pick_dir = pick_dir
        self.root_hint = root_hint
        self.edit = LineEdit()
        self.edit.setText(value)
        btn = ToolButton(FIF.FOLDER if pick_dir else FIF.DOCUMENT)
        btn.clicked.connect(self._browse)
        self.addWidget(self.edit, 1)
        self.addWidget(btn)

    def _browse(self) -> None:
        start = self.edit.text() or self.root_hint
        if self.pick_dir:
            p = QFileDialog.getExistingDirectory(self.parent_widget, "", start)
        else:
            p, _ = QFileDialog.getOpenFileName(self.parent_widget, "", start)
        if p:
            # Если путь внутри корня клиента — храним относительный (читабельнее)
            if (
                self.root_hint
                and p.lower().startswith(self.root_hint.lower().rstrip("\\/") + "/")
                or self.root_hint
                and p.lower().startswith(self.root_hint.lower().rstrip("\\/") + "\\")
            ):
                p = p[len(self.root_hint.rstrip("\\/")) + 1 :]
            self.edit.setText(p)

    def text(self) -> str:
        return self.edit.text().strip()


_CFG_EXISTING = "existing"
_CFG_NEW = "new"


class _ConfigPicker(QWidget):
    """Выбор готового CFG либо явное создание отдельного из шаблона."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings: Settings | None = None
        self.branch = STABLE
        self.mode = MODE_DIAG
        self.preset_name = ""
        self.mission_name = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.combo = ComboBox()
        self.combo.currentIndexChanged.connect(lambda _i: self._update_status())
        layout.addWidget(self.combo)
        self.status = CaptionLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def set_context(
        self,
        settings: Settings,
        branch: str,
        mode: str,
        preset_name: str,
        mission_name: str,
        current_config: str | None = None,
    ) -> None:
        from core.layout import preset_base_name, server_configs

        previous = self.combo.currentData()
        self.settings = settings
        self.branch = branch
        self.mode = mode
        self.preset_name = preset_name
        self.mission_name = mission_name
        desired = (_CFG_EXISTING, current_config) if current_config is not None else previous
        cfgs = server_configs(settings, branch, mode)
        generated = f"serverDZ_{preset_base_name(preset_name, mission_name)}.cfg"

        self.combo.blockSignals(True)
        self.combo.clear()
        selected = 0
        for cfg_name in cfgs:
            self.combo.addItem(
                tr("preset.cfg_use", "Использовать готовый: {n}", n=cfg_name),
                userData=(_CFG_EXISTING, cfg_name),
            )
            if desired == (_CFG_EXISTING, cfg_name):
                selected = self.combo.count() - 1

        preserved = str(desired[1]) if desired and desired[0] == _CFG_EXISTING else ""
        if preserved and preserved not in cfgs:
            self.combo.addItem(
                tr("preset.cfg_current", "Текущий CFG: {n}", n=preserved),
                userData=(_CFG_EXISTING, preserved),
            )
            if desired == (_CFG_EXISTING, preserved):
                selected = self.combo.count() - 1

        self.combo.addItem(
            tr("preset.cfg_create", "Создать отдельный: {n}", n=generated),
            userData=(_CFG_NEW, generated),
        )
        if desired and desired[0] == _CFG_NEW:
            selected = self.combo.count() - 1
        elif not cfgs and not preserved:
            selected = self.combo.count() - 1
        self.combo.setCurrentIndex(selected)
        self.combo.blockSignals(False)
        self._update_status()

    def config_name(self) -> str:
        data = self.combo.currentData()
        return str(data[1]) if data else ""

    def needs_creation(self) -> bool:
        data = self.combo.currentData()
        return bool(data and data[0] == _CFG_NEW)

    def _update_status(self) -> None:
        if self.needs_creation():
            text = tr(
                "preset.cfg_create_note",
                "Новый CFG будет создан из шаблона; существующие файлы не изменятся.",
            )
        else:
            text = tr(
                "preset.cfg_use_note",
                "Выбранный CFG будет использоваться как есть, без копирования.",
            )
        self.status.setText(text)


# Параметры запуска новых пресетов — отладочный набор «как надо»:
# полное логирование на сервере, окно вместо фуллскрина на клиенте,
# быстрый вход/выход. Diag-набор добавляется поверх для режима отладки.
# TimeLogin/TimeLogout в db/globals.xml миссии, секунды. Единица, а не
# ванильные 15: при отладке сервер перезапускают десятки раз за сессию,
# и каждый лишний тик ожидания входа платится живым временем.
_DEFAULT_TIME_LOGIN = 1


def _attach_map_mods(preset: ServerPreset, picker: MapPicker) -> None:
    """Моды карты (из репозитория миссии) автоматически включаются в пресет."""
    from pathlib import Path as _P

    entry = picker.catalog_entry()
    if not entry:
        return
    for spec in getattr(entry, "mods", []):
        mod_name = _P(spec.get("path", "")).name.lstrip("@")
        if mod_name and mod_name not in preset.mods:
            preset.mods.append(mod_name)


# ---------------------------------------------------------------- Расширенный


class AdvancedPresetDialog(ThemedDialog):
    def __init__(self, preset: ServerPreset, settings: Settings, parent=None):
        super().__init__(parent)
        self.preset = preset
        self.settings = settings
        # пара имя+карта на момент открытия: совпадение с самим собой — не конфликт
        from core.layout import preset_key

        self._original_key = preset_key(preset.name, preset.world) if preset.path().exists() else ""
        self.setWindowTitle(tr("preset.edit_title", "Пресет: {n}", n=preset.name))
        self.setMinimumSize(620, 460)
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 760
        self.resize(760, min(680, max(460, available_height - 80)))

        outer_layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setObjectName("presetScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget(scroll)
        content.setObjectName("presetScrollContent")
        content.setAutoFillBackground(False)
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll, 1)

        form = QFormLayout()

        self.name = LineEdit()
        self.name.setText(preset.name)
        form.addRow(tr("preset.name", "Название"), self.name)
        self.name_error = CaptionLabel("")
        self.name_error.setStyleSheet("color:#d32f2f;")
        self.name_error.setWordWrap(True)
        form.addRow("", self.name_error)

        self.mode = ComboBox()
        self.mode.addItem(
            tr("preset.mode_diag", "Diag: DayZDiag_x64 как сервер и клиент (отладка, filepatching)"), userData=MODE_DIAG
        )
        self.mode.addItem(
            tr("preset.mode_dedicated", "Dedicated: отдельный DayZServer_x64 + обычный клиент"), userData=MODE_DEDICATED
        )
        self.mode.setCurrentIndex(0 if preset.mode == MODE_DIAG else 1)
        form.addRow(tr("preset.mode", "Режим запуска"), self.mode)

        self.branch = ComboBox()
        self.branch.addItem("Stable", userData=STABLE)
        self.branch.addItem("Experimental", userData=EXPERIMENTAL)
        self.branch.setCurrentIndex(0 if preset.branch == STABLE else 1)
        form.addRow(tr("preset.branch", "Ветка по умолчанию"), self.branch)

        # доступность режима/ветки — только если нужные exe реально на месте
        diag_ok = bool(settings.client_stable) and (Path(settings.client_stable) / "DayZDiag_x64.exe").is_file()
        dedicated_ok = bool(settings.server_stable) and (Path(settings.server_stable) / "DayZServer_x64.exe").is_file()
        self.mode.setItemEnabled(0, diag_ok)
        self.mode.setItemEnabled(1, dedicated_ok)
        if not diag_ok and self.mode.currentIndex() == 0 and dedicated_ok:
            self.mode.setCurrentIndex(1)
        elif not dedicated_ok and self.mode.currentIndex() == 1 and diag_ok:
            self.mode.setCurrentIndex(0)

        exp_ok = (bool(settings.client_exp) and Path(settings.client_exp).is_dir()) or (
            bool(settings.server_exp) and Path(settings.server_exp).is_dir()
        )
        self.branch.setItemEnabled(1, exp_ok)
        if not exp_ok and self.branch.currentIndex() == 1:
            self.branch.setCurrentIndex(0)

        self.map_picker = MapPicker(self)
        self.map_picker.set_context(
            settings, self._branch_value(), self._mode_value(), preset.name, current_mission=preset.mission
        )
        self.cfg_picker = _ConfigPicker(self)
        self.cfg_picker.set_context(
            settings,
            self._branch_value(),
            self._mode_value(),
            preset.name,
            self.map_picker.mission_name(),
            current_config=preset.server_config,
        )
        self.mode.currentIndexChanged.connect(self._mission_ctx)
        self.branch.currentIndexChanged.connect(self._mission_ctx)
        self.name.textChanged.connect(self._name_changed)
        self.map_picker.changed.connect(self._cfg_ctx)
        self.map_picker.changed.connect(self._files_hint_update)
        self.cfg_picker.combo.currentIndexChanged.connect(self._files_hint_update)
        form.addRow(tr("preset.map", "Карта"), self.map_picker)
        form.addRow(tr("preset.cfg", "Конфигурация сервера"), self.cfg_picker)
        self.files_hint = CaptionLabel("")
        self.files_hint.setWordWrap(True)
        form.addRow("", self.files_hint)
        self._name_changed(preset.name)

        self.port = _NoWheelSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(preset.port)
        form.addRow(tr("preset.port", "Порт"), self.port)

        self.server_ip = LineEdit()
        self.server_ip.setText(preset.server_ip or "127.0.0.1")
        self.server_ip.setPlaceholderText("127.0.0.1")
        self.server_ip.setToolTip(
            tr(
                "preset.server_ip_tip",
                "Адрес сервера, к которому подключается клиент. Для локального сервера — 127.0.0.1.",
            )
        )
        form.addRow(tr("preset.server_ip", "IP сервера"), self.server_ip)

        self.clean_logs = CheckBox(tr("preset.clean_logs", "Очищать логи перед запуском выбранных процессов"))
        self.clean_logs.setChecked(preset.clean_logs)
        self.clean_logs.setToolTip(
            tr(
                "preset.clean_logs_tip",
                "Рекурсивно удаляет .log, .RPT, .ADM и .mdmp. MODS, mpmissions и storage_* не затрагиваются.",
            )
        )
        form.addRow("", self.clean_logs)

        self.time_login = _NoWheelSpinBox()
        self.time_login.setRange(0, 3600)
        self.time_login.setToolTip(
            tr(
                "preset.time_login_tip",
                "TimeLogin и TimeLogout в db\\globals.xml миссии — "
                "таймеры ожидания при входе и выходе. Задаются одним "
                "значением; для отладки удобно 0.",
            )
        )
        self.time_login.setValue(self._read_time_login())
        form.addRow(tr("preset.time_login", "Время на вход/выход (секунды)"), self.time_login)

        clean_row = QHBoxLayout()
        b_admin = PushButton(FIF.PEOPLE, tr("preset.admin_sync", "Актуализировать данные для Admin Tools"))
        b_admin.setToolTip(
            tr(
                "preset.admin_sync_tip",
                "Перезаписывает в профиле списки админов и пароль VPP "
                "из «Настроек» — для COT, VPPAdminTools и LBmaster.",
            )
        )
        b_admin.clicked.connect(self._sync_admin_tools)
        b_open_prof = PushButton(FIF.FOLDER, tr("preset.open_prof", "Открыть папку профиля"))
        b_open_prof.setToolTip(tr("preset.open_prof_tip", "Открывает папку профиля сервера в проводнике."))
        b_open_prof.clicked.connect(self._open_profile)
        clean_row.addWidget(b_admin)
        clean_row.addWidget(b_open_prof)
        clean_row.addStretch(1)
        form.addRow("", clean_row)
        layout.addLayout(form)

        self.params_box = QHBoxLayout()
        layout.addLayout(self.params_box)
        self._param_widgets: dict[tuple[str, str], CheckBox | ComboBox | LineEdit] = {}
        self._rebuild_params()
        self.mode.currentIndexChanged.connect(self._rebuild_params)

        form2 = QFormLayout()
        self.extra_server = LineEdit()
        self.extra_server.setText(preset.extra_server)
        self.extra_server.setToolTip(tr("preset.extra_tip", "Любые дополнительные аргументы командной строки."))
        self.extra_client = LineEdit()
        self.extra_client.setText(preset.extra_client)
        self.extra_client.setToolTip(self.extra_server.toolTip())
        form2.addRow(tr("preset.extra_server", "Доп. аргументы сервера"), self.extra_server)
        form2.addRow(tr("preset.extra_client", "Доп. аргументы клиента"), self.extra_client)
        layout.addLayout(form2)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_save = PrimaryPushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        b_save.setObjectName("presetSaveButton")
        b_save.clicked.connect(self._save)
        btns.addWidget(b_cancel)
        btns.addWidget(b_save)
        outer_layout.addLayout(btns)

    def _branch_value(self) -> str:
        return str(self.branch.currentData() or STABLE)

    def _mode_value(self) -> str:
        return str(self.mode.currentData() or MODE_DEDICATED)

    def _profile_dir(self) -> str:
        """Абсолютный путь папки профиля для текущих значений формы."""
        from core.layout import resolve_profiles, preset_base_name

        profiles = self.preset.profiles or preset_base_name(self.name.text().strip(), self.map_picker.mission_name())
        return resolve_profiles(profiles, self.settings, self._branch_value(), self._mode_value())

    def _open_profile(self) -> None:
        import os
        from qfluentwidgets import InfoBar, InfoBarPosition

        path = self._profile_dir()
        if not path or not Path(path).is_dir():
            InfoBar.warning(
                title=tr("preset.no_profile", "Папки профиля ещё нет — она создастся при запуске."),
                content=path or "",
                parent=self,
                duration=5000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        os.startfile(path)  # noqa: S606 — открытие проводника по своей же папке

    def _sync_admin_tools(self) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        from core.admin_tools import apply as apply_admin_rights

        s = self.settings
        if not s.admin_steamids and not s.admin_password.strip():
            InfoBar.warning(
                title=tr("preset.admin_sync_empty", "В настройках не заданы ни SteamID админов, ни пароль."),
                content="",
                parent=self,
                duration=5000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        # mods=None — обновляем обе админки: какая из них подключена к пресету,
        # тут неважно, лишние файлы никому не мешают
        done = apply_admin_rights(self._profile_dir(), None, s.admin_steamids, s.admin_password)
        InfoBar.success(
            title=tr("preset.admin_synced", "Обновлено админок: {n}", n=len(done)),
            content=", ".join(t.title for t, _ in done),
            parent=self,
            duration=4000,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _read_time_login(self) -> int:
        """Актуальное значение из globals.xml миссии; иначе из пресета;
        иначе значение по умолчанию."""
        from pathlib import Path as _P
        from core.layout import resolve_mission
        from core.missions import read_global_var

        p = self.preset
        mission = resolve_mission(p.mission, self.settings, p.branch, p.mode)
        if mission:
            val = read_global_var(_P(mission), "TimeLogin")
            if val is not None:
                try:
                    return int(float(val))
                except ValueError:
                    pass
        return p.time_login if p.time_login >= 0 else _DEFAULT_TIME_LOGIN

    def _mission_ctx(self) -> None:
        self.map_picker.set_context(
            self.settings,
            self._branch_value(),
            self._mode_value(),
            self.name.text().strip(),
            current_mission=self.map_picker.mission_name(),
        )
        self._cfg_ctx()

    def _cfg_ctx(self) -> None:
        self.cfg_picker.set_context(
            self.settings,
            self._branch_value(),
            self._mode_value(),
            self.name.text().strip(),
            self.map_picker.mission_name(),
        )

    def _name_changed(self, name: str) -> None:
        self.name.setError(False)
        self.name_error.setText("")
        self.map_picker.set_preset_name(name.strip())
        self._cfg_ctx()

    def _files_hint_update(self) -> None:
        from core.layout import PROFILE_SUBDIR

        self.files_hint.setText(
            tr(
                "preset.files_hint",
                "CFG: {c}; профиль: общий {p}; миссия: {m}.",
                c=self.cfg_picker.config_name() or "?",
                p=PROFILE_SUBDIR,
                m=self.map_picker.mission_name() or "?",
            )
        )

    # Параметры: FLAG -> чекбокс; SWITCH -> комбо (—/вкл/выкл); INT/STR -> строка
    def _rebuild_params(self) -> None:
        while self.params_box.count():
            item = self.params_box.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
        self._param_widgets = {}
        diag = self._mode_value() == MODE_DIAG
        for target, title, values in (
            (SERVER, tr("preset.params_server", "Параметры сервера"), self.preset.params_server),
            (CLIENT, tr("preset.params_client", "Параметры клиента"), self.preset.params_client),
        ):
            values = dict(values)
            if diag:
                # При выборе Diag обязательный отладочный набор включается
                # сразу и отображается в форме, даже у старого пресета.
                values.update(default_params(target, diag=True))
            box = QGroupBox(title)
            f = QFormLayout(box)
            for spec in specs_for(target, diag):
                if not diag and spec.name == "filePatching":
                    continue
                if spec.ptype == FLAG:
                    w = CheckBox()
                    w.setChecked(bool(values.get(spec.name, False)))
                elif spec.ptype == SWITCH:
                    w = ComboBox()
                    w.addItem("—", userData=None)
                    w.addItem(tr("preset.sw_on", "включено (=1)"), userData=True)
                    w.addItem(tr("preset.sw_off", "выключено (=0)"), userData=False)
                    cur = values.get(spec.name, None)
                    w.setCurrentIndex(0 if cur is None else (1 if cur else 2))
                else:
                    w = LineEdit()
                    w.setText(str(values.get(spec.name, "")))
                    if spec.ptype == INT:
                        w.setPlaceholderText(tr("preset.int_ph", "число или пусто"))
                w.setToolTip(spec.tooltip())
                label = BodyLabel(f"-{spec.name}")
                label.setToolTip(spec.tooltip())
                f.addRow(label, w)
                self._param_widgets[(target, spec.name)] = w
            self.params_box.addWidget(box)

    def _collect_params(self, target: str) -> dict:
        out = {}
        diag = self._mode_value() == MODE_DIAG
        for spec in specs_for(target, diag):
            w = self._param_widgets.get((target, spec.name))
            if w is None:
                continue
            if spec.ptype == FLAG and isinstance(w, CheckBox):
                if w.isChecked():
                    out[spec.name] = True
            elif spec.ptype == SWITCH and isinstance(w, ComboBox):
                val = w.currentData()
                if val is not None:
                    out[spec.name] = val
            elif isinstance(w, LineEdit):
                text = w.text().strip()
                if text:
                    if spec.ptype == INT:
                        try:
                            out[spec.name] = int(text)
                        except ValueError:
                            continue
                    else:
                        out[spec.name] = text
        return out

    def _save(self) -> None:
        from core.layout import valid_name, name_conflict, create_server_config, PROFILE_SUBDIR, rename_preset_files

        p = self.preset
        new_name = self.name.text().strip() or p.name
        if not valid_name(new_name):
            problem = tr(
                "preset.bad_name_full",
                "Недопустимое название. Разрешены только латинские буквы, "
                "цифры, «-» и «_» — без кириллицы и пробелов, "
                "и начинаться оно должно с буквы. "
                "Например: my_test_server",
            )
            self.name.setError(True)
            self.name.setToolTip(problem)
            self.name_error.setText(problem)
            return
        world = self.map_picker.world()
        conflict = name_conflict(new_name, world, current_key=self._original_key)
        if conflict:
            self.name.setError(True)
            self.name.setToolTip(conflict)
            self.name_error.setText(conflict)
            return
        if new_name != p.name:
            rename_preset_files(self.settings, self._branch_value(), self._mode_value(), p.name, new_name, world)
            p.name = new_name  # save() сам уберёт старый файл пресета
            self.map_picker.set_preset_name(new_name)
        p.mode = self._mode_value()
        p.branch = self._branch_value()
        p.mission = self.map_picker.mission_name()
        if self.cfg_picker.needs_creation():
            try:
                p.server_config = create_server_config(self.settings, p.branch, p.mode, p.name, p.mission)
            except RuntimeError:
                p.server_config = self.cfg_picker.config_name()
        else:
            p.server_config = self.cfg_picker.config_name()
        p.profiles = PROFILE_SUBDIR
        _attach_map_mods(p, self.map_picker)
        p.server_ip = self.server_ip.text().strip() or "127.0.0.1"
        p.port = self.port.value()
        p.time_login = self.time_login.value()
        p.clean_logs = self.clean_logs.isChecked()
        # применяем сразу, если миссия уже на диске (иначе — перед запуском)
        from pathlib import Path as _P
        from core.layout import resolve_mission
        from core.missions import set_global_var

        mission_path = resolve_mission(p.mission, self.settings, p.branch, p.mode)
        if mission_path and _P(mission_path).is_dir():
            set_global_var(_P(mission_path), "TimeLogin", str(p.time_login))
            set_global_var(_P(mission_path), "TimeLogout", str(p.time_login))
        p.params_server = self._collect_params(SERVER)
        p.params_client = self._collect_params(CLIENT)
        p.extra_server = self.extra_server.text().strip()
        p.extra_client = self.extra_client.text().strip()
        p.save()
        self.map_picker.ensure_mission()  # миссии нет — стартует модальная загрузка
        self.accept()


# ---------------------------------------------------------------- Ленивый мастер


class LazyPresetWizard(ThemedWizard):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.result_preset: ServerPreset | None = None
        self.setWindowTitle(tr("preset.lazy_title", "Новый пресет — простой режим"))
        self.resize(640, 480)

        # Шаг 1: имя и режим
        p1 = QWizardPage()
        p1.setTitle(tr("preset.lazy_p1", "Название и режим"))
        l1 = QVBoxLayout(p1)
        self.name = LineEdit()
        self.name.setPlaceholderText(tr("preset.lazy_name_ph", "Например: my_test_server"))
        self.name.textChanged.connect(lambda _t: self._clear_name_error())
        l1.addWidget(BodyLabel(tr("preset.name", "Название")))
        l1.addWidget(self.name)
        self.name_error = CaptionLabel("")
        self.name_error.setStyleSheet("color:#d32f2f;")
        self.name_error.setWordWrap(True)
        l1.addWidget(self.name_error)
        l1.addSpacing(12)
        self.rb_diag = RadioButton(tr("preset.lazy_diag", "Отладка модов (Diag) — рекомендуется для разработки"))
        diag_desc = CaptionLabel(
            tr("preset.lazy_diag_desc", "Игра запускается в диагностическом режиме, работает filepatching.")
        )
        diag_desc.setContentsMargins(28, 0, 0, 0)
        self.rb_dedicated = RadioButton(
            tr("preset.lazy_dedicated", "Обычный сервер (Dedicated) — как «настоящий» сервер")
        )
        ded_desc = CaptionLabel(tr("preset.lazy_dedicated_desc", "Отдельная серверная программа + обычный клиент."))
        ded_desc.setContentsMargins(28, 0, 0, 0)
        self.rb_diag.setChecked(True)
        l1.addWidget(self.rb_diag)
        l1.addWidget(diag_desc)
        l1.addSpacing(8)
        l1.addWidget(self.rb_dedicated)
        l1.addWidget(ded_desc)
        l1.addStretch(1)

        # доступность режимов — только если нужный exe реально на месте
        diag_ok = bool(settings.client_stable) and (Path(settings.client_stable) / "DayZDiag_x64.exe").is_file()
        dedicated_ok = bool(settings.server_stable) and (Path(settings.server_stable) / "DayZServer_x64.exe").is_file()
        if not diag_ok:
            self.rb_diag.setEnabled(False)
            diag_desc.setEnabled(False)
            no_diag = tr("preset.lazy_diag_missing", "DayZDiag_x64.exe не найден — укажите папку игры в «Настройках».")
            self.rb_diag.setToolTip(no_diag)
            diag_desc.setToolTip(no_diag)
        if not dedicated_ok:
            self.rb_dedicated.setEnabled(False)
            ded_desc.setEnabled(False)
            no_ded = tr(
                "preset.lazy_dedicated_missing", "DayZServer_x64.exe не найден — укажите папку сервера в «Настройках»."
            )
            self.rb_dedicated.setToolTip(no_ded)
            ded_desc.setToolTip(no_ded)
        if not diag_ok and dedicated_ok:
            self.rb_dedicated.setChecked(True)
        p1.registerField("name*", self.name)
        self.addPage(p1)

        # Шаг 2: готовые ресурсы либо явное создание отдельных
        p2 = QWizardPage()
        p2.setTitle(tr("preset.lazy_p2", "Миссия и конфигурация"))
        l2 = QFormLayout(p2)
        self.map_picker = MapPicker(p2)
        self.cfg_picker = _ConfigPicker(p2)
        self.rb_diag.toggled.connect(lambda _on: self._sync_map_ctx())
        self.map_picker.changed.connect(self._resources_changed)
        self.cfg_picker.combo.currentIndexChanged.connect(self._update_note)
        l2.addRow(tr("preset.map", "Миссия"), self.map_picker)
        l2.addRow(tr("preset.cfg", "Конфигурация сервера"), self.cfg_picker)
        self.auto_note = CaptionLabel("")
        self.auto_note.setWordWrap(True)
        l2.addRow("", self.auto_note)
        self.addPage(p2)
        self._p2 = p2

        # Шаг 3: финиш
        p3 = QWizardPage()
        p3.setTitle(tr("common.done", "Готово"))
        l3 = QVBoxLayout(p3)
        l3.addWidget(
            BodyLabel(
                tr(
                    "preset.lazy_done",
                    "Пресет будет создан с разумными настройками по умолчанию.\n"
                    "Моды подключаются на вкладке «Моды», параметры — в «Расширенном» редакторе.",
                )
            )
        )
        self.addPage(p3)

        self.currentIdChanged.connect(self._page_changed)

    def _sync_map_ctx(self) -> None:
        mode = MODE_DIAG if self.rb_diag.isChecked() else MODE_DEDICATED
        self.map_picker.set_context(self.settings, STABLE, mode, self.name.text().strip())
        self._sync_cfg_ctx()

    def _sync_cfg_ctx(self) -> None:
        mode = MODE_DIAG if self.rb_diag.isChecked() else MODE_DEDICATED
        self.cfg_picker.set_context(
            self.settings,
            STABLE,
            mode,
            self.name.text().strip(),
            self.map_picker.mission_name(),
        )

    def _resources_changed(self) -> None:
        self._sync_cfg_ctx()
        self._update_note()

    def _page_changed(self, _id: int) -> None:
        if self.currentPage() is self._p2:
            self._sync_map_ctx()
            self._update_note()

    def _update_note(self) -> None:
        from core.layout import PROFILE_SUBDIR

        self.auto_note.setText(
            tr(
                "preset.lazy_auto",
                "Миссия: {m}\nCFG: {c}\nПрофиль общий: {p}",
                m=self.map_picker.mission_name() or "?",
                c=self.cfg_picker.config_name() or "?",
                p=PROFILE_SUBDIR,
            )
        )

    def _clear_name_error(self) -> None:
        self.name.setError(False)
        self.name_error.setText("")

    def validateCurrentPage(self) -> bool:  # имя метода задаёт Qt
        from core.layout import valid_name, name_conflict

        if self.currentId() == 0:
            name = self.name.text().strip()
            problem = ""
            if not valid_name(name):
                problem = tr(
                    "preset.bad_name_full",
                    "Недопустимое название. Разрешены только латинские буквы, "
                    "цифры, «-» и «_» — без кириллицы и пробелов, "
                    "и начинаться оно должно с буквы. "
                    "Например: my_test_server",
                )
            else:
                problem = name_conflict(name)
            if problem:
                self.name.setError(True)
                self.name.setToolTip(problem)
                self.name_error.setText(problem)
                return False
        return super().validateCurrentPage()

    def accept(self) -> None:
        from core.layout import create_server_config, name_conflict, PROFILE_SUBDIR

        diag = self.rb_diag.isChecked()
        name = self.name.text().strip()
        mode = MODE_DIAG if diag else MODE_DEDICATED
        mission = self.map_picker.mission_name()
        conflict = name_conflict(name, self.map_picker.world())
        if conflict:
            self.auto_note.setText(conflict)
            return
        if self.cfg_picker.needs_creation():
            try:
                config = create_server_config(self.settings, STABLE, mode, name, mission)
            except RuntimeError as e:
                self.auto_note.setText(str(e))
                return
        else:
            config = self.cfg_picker.config_name()
        preset = ServerPreset(
            name=name,
            mode=mode,
            server_config=config,
            mission=mission,
            profiles=PROFILE_SUBDIR,
            time_login=_DEFAULT_TIME_LOGIN,
        )
        preset.params_server = default_params(SERVER, diag)
        preset.params_client = default_params(CLIENT, diag)
        _attach_map_mods(preset, self.map_picker)
        preset.save()
        self.result_preset = preset
        self.map_picker.ensure_mission()  # миссии нет — стартует модальная загрузка
        self._apply_default_time_login(preset)
        super().accept()

    def _apply_default_time_login(self, preset: ServerPreset) -> None:
        """Записывает наше умолчание в globals.xml только что созданной миссии.

        Миссии приезжают с TimeLogin = 15. Редактор показывает фактическое
        значение из миссии, а не из пресета — так и надо, иначе он врал бы про
        то, что реально произойдёт на сервере. Но из-за этого умолчание в
        коде до миссии не доходило: открыл пресет — увидел 15, сохранил — 15
        уехало и в пресет.

        Поэтому пишем сразу при создании, пока значение заведомо ничьё. Чужой
        выбор при этом не затирается: существующие пресеты сюда не попадают.
        """
        from pathlib import Path as _P

        from core.layout import resolve_mission
        from core.missions import set_global_var

        mission = resolve_mission(preset.mission, self.settings, preset.branch, preset.mode)
        if not mission or not _P(mission).is_dir():
            return  # миссию не скачали — применится при первом запуске
        try:
            set_global_var(_P(mission), "TimeLogin", str(preset.time_login))
            set_global_var(_P(mission), "TimeLogout", str(preset.time_login))
        except OSError:
            pass  # не записалось — не повод срывать создание пресета
