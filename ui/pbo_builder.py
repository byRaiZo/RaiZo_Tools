"""Оригинальный PBO Builder byRaiZo как вкладка RaiZo Tools."""

from __future__ import annotations

import html
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox

from core import packer, pbo_context_menu
from core.pbobuilder.build import build_all
from core.pbobuilder.constants import DEFAULT_EXCLUDE_PATTERNS, DEFAULT_PROJECT_ROOT, DEFAULT_TEMP_DIR
from core.pbobuilder.errors import BuildError
from core.pbobuilder.files import clear_full_temp_folder
from core.pbobuilder.models import BuildConfig, BuildResult
from core.pbobuilder.preflight import PREFLIGHT_CHECK_DEFAULTS, PreflightResult, run_preflight_for_targets
from core.pbobuilder.system import (
    create_build_log_path,
    get_app_data_dir,
    get_default_max_processes,
    get_initial_dir_from_value,
    get_logs_dir,
    load_build_cache,
    save_build_cache,
)
from core.pbobuilder.targets import detect_addon_targets
from core.settings import RES_DIR, Settings
from ui.theme import BRAND_ERROR, BRAND_INFO, BRAND_SUCCESS, BRAND_WARNING, apply_pbo_style

APP_TITLE = "RaiZo Tools — PBO Builder"
ASSETS_DIR = RES_DIR / "core" / "pbobuilder" / "assets"


TEXT = {
    "ru": {
        "settings": "Настройки",
        "language": "Язык",
        "russian": "Русский",
        "english": "Английский",
        "private_key": "Приватный ключ",
        "project_root": "Корень проекта",
        "temp_dir": "Папка temp",
        "max_processes": "Макс. процессов",
        "exclude_patterns": "Исключения",
        "logs": "Логи",
        "preflight_checks": "Проверки Preflight",
        "clear_logs": "Очистить логи",
        "logs_folder": "Папка логов",
        "cancel": "Отмена",
        "ok": "Понятно",
        "save": "Сохранить",
        "paths": "Пути",
        "ready": "Готов",
        "source_root": "Исходная папка",
        "output_root_client": "Вывод client",
        "output_root_server": "Вывод server",
        "same_as_client_output": "Как вывод client",
        "pbo_name": "Имя PBO",
        "pbo_name_placeholder": "Опционально для одного аддона",
        "pipeline": "Пайплайн",
        "binarize_p3d": "Бинаризовать P3D",
        "protect_p3d": "Защитить P3D",
        "cpp_rvmat_to_bin": "CPP/RVMAT в BIN",
        "sign_pbos": "Подписывать PBO",
        "force_rebuild": "Полная пересборка",
        "preflight_before_build": "Проверка перед сборкой",
        "actions": "Действия",
        "build_pbos": "Собрать PBO",
        "preflight": "Проверка",
        "clear_all_temp": "Очистить temp",
        "clear_cache": "Очистить кэш",
        "latest_log": "Последний лог",
        "addons": "Аддоны",
        "refresh": "Обновить",
        "all": "Все",
        "none": "Снять",
        "open": "Открыть",
        "browse": "Обзор",
        "add_path": "Добавить: {label}",
        "remove_path": "Удалить выбранный путь: {label}",
        "add_path_title": "Добавить: {label}",
        "language_restart": "Язык будет применён после перезапуска RaiZo Tools.",
        "path_empty": "Путь не задан.",
        "path_missing": "Путь не существует: {path}",
        "field_empty": "{label}: путь не задан.",
        "field_missing": "{label}: путь не существует: {path}",
        "select_source_root": "Выберите исходную папку.",
        "source_root_missing": "Исходная папка не существует: {path}",
        "select_addon_check": "Выберите хотя бы один аддон для проверки.",
        "select_addon_build": "Выберите хотя бы один аддон для сборки.",
        "select_output_client": "Выберите папку вывода client.",
        "pbo_override_single": "Своё имя PBO можно задать только для одного аддона.",
        "select_required": "Выберите {label}.",
        "file_missing": "{label} не существует: {path}",
        "output_inside": "Папка результата не должна находиться внутри исходников.",
        "protect_requires_binarize": "Защита P3D требует включённой бинаризации P3D.",
        "build_running_status": "Сборка...",
        "preflight_running_status": "Проверка...",
        "working_status": "Работа {current}/{maximum}",
        "build_finished_status": "Сборка OK",
        "preflight_finished_status": "Проверка OK",
        "error_status": "Ошибка",
        "build_finished_message": "Сборка завершена.",
        "preflight_errors": "Проверка завершена: ошибок — {errors}, предупреждений — {warnings}.",
        "preflight_warnings": "Проверка завершена с предупреждениями: {warnings}.",
        "preflight_ok": "Проверка завершена без ошибок и предупреждений.",
        "build_progress_title": "Сборка PBO",
        "build_progress_message": "Идёт сборка...",
        "build_log": "Лог сборки",
        "preflight_log": "Лог проверки",
        "open_file": "Открыть файл",
        "close": "Закрыть",
        "cannot_clear_logs": "Нельзя очищать логи во время сборки.",
        "logs_empty": "Папка логов уже пуста.",
        "logs_cleared": "Удалено файлов логов: {count}.",
        "cannot_clear_all_temp": "Нельзя очищать temp во время сборки.",
        "clear_all_temp_confirm": "Очистить всё содержимое temp-папки?\n\n{path}",
        "clear_all_temp_title": "Очистка temp",
        "clear_all_temp_action": "Очистить temp",
        "all_temp_cleared": "Содержимое temp-папки очищено.",
        "cannot_clear_cache": "Нельзя очищать кэш во время сборки.",
        "select_addon": "Выберите хотя бы один аддон.",
        "clear_cache_confirm": "Очистить кэш выбранных аддонов?",
        "clear_cache_title": "Очистка кэша",
        "clear_cache_action": "Очистить кэш",
        "cache_cleared": "Очищено записей кэша: {count}.",
        "no_build_logs": "Логи сборки пока не найдены.",
        "context_menu": "Контекстное меню Windows",
        "install_context_menu": "Установить пункт меню",
        "remove_context_menu": "Удалить пункт меню",
        "context_menu_installed": "Пункт «Собрать PBO» установлен.",
        "context_menu_not_installed": "Пункт «Собрать PBO» не установлен.",
        "context_menu_error": "Не удалось изменить контекстное меню: {error}",
    },
    "en": {
        "settings": "Settings",
        "language": "Language",
        "russian": "Russian",
        "english": "English",
        "private_key": "Private key",
        "project_root": "Project root",
        "temp_dir": "Temp dir",
        "max_processes": "Max processes",
        "exclude_patterns": "Exclude patterns",
        "logs": "Logs",
        "preflight_checks": "Preflight checks",
        "clear_logs": "Clear logs",
        "logs_folder": "Logs folder",
        "cancel": "Cancel",
        "ok": "OK",
        "save": "Save",
        "paths": "Paths",
        "ready": "Ready",
        "source_root": "Source root",
        "output_root_client": "Output root client",
        "output_root_server": "Output root server",
        "same_as_client_output": "Same as client output",
        "pbo_name": "PBO name",
        "pbo_name_placeholder": "Optional for single addon",
        "pipeline": "Pipeline",
        "binarize_p3d": "Binarize P3D",
        "protect_p3d": "Protect P3D",
        "cpp_rvmat_to_bin": "CPP/RVMAT to BIN",
        "sign_pbos": "Sign PBOs",
        "force_rebuild": "Force rebuild",
        "preflight_before_build": "Preflight before build",
        "actions": "Actions",
        "build_pbos": "Build PBOs",
        "preflight": "Preflight",
        "clear_all_temp": "Clear all temp",
        "clear_cache": "Clear cache",
        "latest_log": "Latest log",
        "addons": "Addons",
        "refresh": "Refresh",
        "all": "All",
        "none": "None",
        "open": "Open",
        "browse": "Browse",
        "add_path": "Add {label}",
        "remove_path": "Remove selected {label}",
        "add_path_title": "Add {label}",
        "language_restart": "Language will be applied after RaiZo Tools restarts.",
        "path_empty": "Path is empty.",
        "path_missing": "Path does not exist: {path}",
        "field_empty": "{label} is empty.",
        "field_missing": "{label} does not exist: {path}",
        "select_source_root": "Select a source root folder.",
        "source_root_missing": "Source root does not exist: {path}",
        "select_addon_check": "Select at least one addon to check.",
        "select_addon_build": "Select at least one addon to build.",
        "select_output_client": "Select an output root client folder.",
        "pbo_override_single": "PBO name override can only be used with one selected addon.",
        "select_required": "Select {label}.",
        "file_missing": "{label} does not exist: {path}",
        "output_inside": "Output folder must not be inside the source folder.",
        "protect_requires_binarize": "P3D protection requires P3D binarization.",
        "build_running_status": "Build running...",
        "preflight_running_status": "Preflight running...",
        "working_status": "Working {current}/{maximum}",
        "build_finished_status": "Build OK",
        "preflight_finished_status": "Preflight OK",
        "error_status": "Error",
        "build_finished_message": "Build finished.",
        "preflight_errors": "Preflight finished with {errors} error(s) and {warnings} warning(s).",
        "preflight_warnings": "Preflight finished with {warnings} warning(s).",
        "preflight_ok": "Preflight finished without errors or warnings.",
        "build_progress_title": "PBO build",
        "build_progress_message": "Build in progress...",
        "build_log": "Build log",
        "preflight_log": "Preflight log",
        "open_file": "Open file",
        "close": "Close",
        "cannot_clear_logs": "Cannot clear logs while a build is running.",
        "logs_empty": "Logs folder is already empty.",
        "logs_cleared": "Deleted {count} log file(s).",
        "cannot_clear_all_temp": "Cannot clear temp while a build is running.",
        "clear_all_temp_confirm": "Clear all selected temp folder contents?\n\n{path}",
        "clear_all_temp_title": "Clear temp",
        "clear_all_temp_action": "Clear temp",
        "all_temp_cleared": "All temp folder contents cleared.",
        "cannot_clear_cache": "Cannot clear cache while a build is running.",
        "select_addon": "Select at least one addon.",
        "clear_cache_confirm": "Clear build cache for selected addons?",
        "clear_cache_title": "Clear cache",
        "clear_cache_action": "Clear cache",
        "cache_cleared": "Cleared {count} cache entries.",
        "no_build_logs": "No build logs found yet.",
        "context_menu": "Windows context menu",
        "install_context_menu": "Install menu entry",
        "remove_context_menu": "Remove menu entry",
        "context_menu_installed": "The Pack PBO entry is installed.",
        "context_menu_not_installed": "The Pack PBO entry is not installed.",
        "context_menu_error": "Could not change the context menu: {error}",
    },
}

PREFLIGHT_LABELS = {
    "preflight_check_cfgpatches": "CfgPatches",
    "preflight_check_required_addons": "requiredAddons[]",
    "preflight_check_cfgmods": "CfgMods scripts",
    "preflight_check_references": "Text references",
    "preflight_check_p3d_internal": "P3D internal refs",
    "preflight_check_case_conflicts": "Case conflicts",
    "preflight_check_risky_paths": "Risky paths",
    "preflight_check_prefix": "PBO prefix",
    "preflight_check_terrain_wrp": "Terrain / WRP",
    "preflight_check_terrain_navmesh": "Navmesh",
    "preflight_check_terrain_road_shapes": "Road shapes",
    "preflight_check_terrain_layers": "Terrain layers",
    "preflight_check_terrain_source_exports": "Source/export warnings",
    "preflight_check_terrain_size": "Terrain size",
}


def _language(value: str) -> str:
    return "en" if value.lower().startswith("en") else "ru"


def _t(key: str, language: str, **values: object) -> str:
    text = TEXT[_language(language)].get(key, TEXT["en"].get(key, key))
    return text.format(**values)


def _show_message(parent: QWidget, message: str, language: str, title: str = APP_TITLE) -> None:
    """Единый однокнопочный Fluent-диалог вместо системного QMessageBox."""
    box = MessageBox(title, message, parent.window())
    box.yesButton.setText(_t("ok", language))
    box.cancelButton.hide()
    box.exec()


def _confirm(parent: QWidget, title: str, message: str, action: str, language: str) -> bool:
    """Подтверждение в стиле остальных опасных действий RaiZo Tools."""
    box = MessageBox(title, message, parent.window())
    box.yesButton.setText(action)
    box.cancelButton.setText(_t("cancel", language))
    return bool(box.exec())


def _set_button_icon(button: QToolButton, filename: str, fallback: QIcon, size: int) -> None:
    path = ASSETS_DIR / filename
    button.setIcon(QIcon(str(path)) if path.is_file() else fallback)
    button.setIconSize(QSize(size, size))


def _open_path(parent: QWidget, path: str) -> None:
    del parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class PathRow(QWidget):
    changed = Signal()

    def __init__(
        self,
        label: str,
        value: str = "",
        browse_kind: str = "folder",
        file_filter: str = "All files (*.*)",
        parent: QWidget | None = None,
        language: str = "ru",
    ) -> None:
        super().__init__(parent)
        self.browse_kind = browse_kind
        self.file_filter = file_filter
        self.language = language
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(3)
        self.label = QLabel(label)
        self.label.setObjectName("FieldLabel")
        self.edit = QLineEdit(value)
        self.edit.setFixedHeight(25)
        self.edit.textChanged.connect(self.changed.emit)
        self.open_button = QToolButton()
        self.open_button.setObjectName("PathIconButton")
        _set_button_icon(
            self.open_button,
            "folder.png",
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            17,
        )
        self.open_button.setToolTip(_t("open", language))
        self.open_button.clicked.connect(self.open_path)
        self.browse_button = QToolButton()
        self.browse_button.setObjectName("PathIconButton")
        self.browse_button.setText("...")
        self.browse_button.setToolTip(_t("browse", language))
        self.browse_button.clicked.connect(self.browse)
        layout.addWidget(self.label, 0, 0, 1, 3)
        layout.addWidget(self.edit, 1, 0)
        layout.addWidget(self.open_button, 1, 1)
        layout.addWidget(self.browse_button, 1, 2)
        layout.setColumnStretch(0, 1)

    def text(self) -> str:
        return self.edit.text().strip()

    def browse(self) -> None:
        initial = get_initial_dir_from_value(self.text())
        if self.browse_kind == "file":
            path, _ = QFileDialog.getOpenFileName(self, self.label.text(), initial, self.file_filter)
        else:
            path = QFileDialog.getExistingDirectory(self, self.label.text(), initial)
        if path:
            self.edit.setText(path.rstrip("\\/") if len(path) > 3 else path.rstrip("\\/"))

    def open_path(self) -> None:
        value = self.text()
        target = value if os.path.isdir(value) else os.path.dirname(value)
        if not value:
            _show_message(self, _t("path_empty", self.language), self.language)
        elif not target or not os.path.isdir(target):
            _show_message(self, _t("path_missing", self.language, path=value), self.language)
        else:
            _open_path(self, target)


class SourceRootRow(QWidget):
    changed = Signal()

    def __init__(
        self,
        label: str,
        current: str = "",
        sources: list[str] | None = None,
        parent: QWidget | None = None,
        language: str = "ru",
        empty_label: str = "",
    ) -> None:
        super().__init__(parent)
        self.path_label = label
        self.language = language
        self._updating = False
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(1)
        label_widget = QLabel(label)
        label_widget.setObjectName("FieldLabel")
        self.combo = QComboBox()
        self.combo.setEditable(False)
        self.combo.setFixedHeight(28)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.add_button = QToolButton()
        self.add_button.setObjectName("PathIconButton")
        _set_button_icon(self.add_button, "plus.png", QIcon(), 15)
        self.add_button.setToolTip(_t("add_path", language, label=label))
        self.remove_button = QToolButton()
        self.remove_button.setObjectName("PathIconButton")
        _set_button_icon(self.remove_button, "minus.png", QIcon(), 15)
        self.remove_button.setToolTip(_t("remove_path", language, label=label))
        self.open_button = QToolButton()
        self.open_button.setObjectName("PathIconButton")
        _set_button_icon(
            self.open_button,
            "folder.png",
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            17,
        )
        self.open_button.setToolTip(_t("open", language))
        layout.addWidget(label_widget, 0, 0, 1, 4)
        layout.addWidget(self.combo, 1, 0)
        layout.addWidget(self.add_button, 1, 1)
        layout.addWidget(self.remove_button, 1, 2)
        layout.addWidget(self.open_button, 1, 3)
        layout.setColumnStretch(0, 1)
        if empty_label:
            self.combo.addItem(empty_label, "")
        for source in self._normalized_sources(current, sources or []):
            self._add_item(source)
        if current:
            self.set_text(current)
        elif empty_label:
            self.combo.setCurrentIndex(0)
        self.combo.currentIndexChanged.connect(self._changed)
        self.add_button.clicked.connect(self.add_source_root)
        self.remove_button.clicked.connect(self.remove_source_root)
        self.open_button.clicked.connect(self.open_path)

    @staticmethod
    def _key(value: str) -> str:
        return os.path.normcase(os.path.normpath(value.strip()))

    @classmethod
    def _normalized_sources(cls, current: str, sources: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for source in [current, *sources]:
            value = source.strip()
            key = cls._key(value)
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    @staticmethod
    def _display_name(value: str) -> str:
        clean = value.rstrip("\\/")
        return os.path.basename(os.path.normpath(clean)) or clean

    def _add_item(self, value: str) -> None:
        if value and self.find_source_index(value) < 0:
            self.combo.addItem(self._display_name(value), value)

    def find_source_index(self, value: str) -> int:
        key = self._key(value)
        for index in range(self.combo.count()):
            data = self.combo.itemData(index)
            stored = str(data) if data is not None else self.combo.itemText(index)
            if self._key(stored) == key:
                return index
        return -1

    def text(self) -> str:
        index = self.combo.currentIndex()
        return str(self.combo.itemData(index) or "").strip() if index >= 0 else ""

    def set_text(self, value: str) -> None:
        value = value.strip()
        self._updating = True
        try:
            self._add_item(value)
            self.combo.setCurrentIndex(self.find_source_index(value))
            self.combo.setToolTip(value)
        finally:
            self._updating = False
        self.changed.emit()

    def source_roots(self) -> list[str]:
        return self._normalized_sources(
            self.text(),
            [str(self.combo.itemData(index) or "") for index in range(self.combo.count())],
        )

    def _changed(self) -> None:
        if not self._updating:
            self.combo.setToolTip(self.text())
            self.changed.emit()

    def add_source_root(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            _t("add_path_title", self.language, label=self.path_label),
            get_initial_dir_from_value(self.text()),
        )
        if path:
            self.set_text(path.rstrip("\\/") if len(path) > 3 else path.rstrip("\\/"))

    def remove_source_root(self) -> None:
        index = self.combo.currentIndex()
        if index < 0 or not self.text():
            return
        self._updating = True
        try:
            self.combo.removeItem(index)
            if self.combo.count():
                self.combo.setCurrentIndex(min(index, self.combo.count() - 1))
        finally:
            self._updating = False
        self.changed.emit()

    def open_path(self) -> None:
        value = self.text()
        if not value:
            _show_message(self, _t("field_empty", self.language, label=self.path_label), self.language)
        elif not os.path.isdir(value):
            _show_message(
                self,
                _t("field_missing", self.language, label=self.path_label, path=value),
                self.language,
            )
        else:
            _open_path(self, value)


class BuildProgressDialog(QDialog):
    def __init__(self, parent: QWidget, language: str) -> None:
        super().__init__(parent)
        self._allow_close = False
        self.setWindowTitle(_t("build_progress_title", language))
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        apply_pbo_style(self)
        self.setFixedSize(320, 120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        label = QLabel(_t("build_progress_message", language))
        label.setObjectName("DialogTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        layout.addWidget(progress)

    def closeEvent(self, event: Any) -> None:
        if self._allow_close:
            super().closeEvent(event)
        else:
            event.ignore()

    def finish(self) -> None:
        self._allow_close = True
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, values: dict[str, Any], owner: "PboBuilderPage") -> None:
        super().__init__(owner)
        self.owner = owner
        self.language = owner.current_language
        self.setWindowTitle(_t("settings", self.language))
        apply_pbo_style(self)
        self.resize(860, 640)
        self.setMinimumSize(760, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)
        title = QLabel(_t("settings", self.language))
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        tools_card = QFrame()
        tools_card.setObjectName("Card")
        tools_layout = QVBoxLayout(tools_card)
        tools_layout.setContentsMargins(12, 12, 12, 12)
        tools_layout.setSpacing(8)
        self.binarize_row = PathRow(
            "binarize.exe", values["binarize_exe"], "file", "Executable (*.exe)", language=self.language
        )
        self.cfgconvert_row = PathRow(
            "CfgConvert.exe", values["cfgconvert_exe"], "file", "Executable (*.exe)", language=self.language
        )
        self.obfuscator_row = PathRow(
            "P3DObfuscator.exe", values["p3d_obfuscator_exe"], "file", "Executable (*.exe)", language=self.language
        )
        self.sign_row = PathRow(
            "DSSignFile.exe", values["dssignfile_exe"], "file", "Executable (*.exe)", language=self.language
        )
        self.key_row = PathRow(
            _t("private_key", self.language),
            values["private_key"],
            "file",
            "BI private key (*.biprivatekey)",
            language=self.language,
        )
        self.project_row = PathRow(_t("project_root", self.language), values["project_root"], language=self.language)
        self.temp_row = PathRow(_t("temp_dir", self.language), values["temp_dir"], language=self.language)
        for row in (
            self.binarize_row,
            self.cfgconvert_row,
            self.obfuscator_row,
            self.sign_row,
            self.key_row,
            self.project_row,
            self.temp_row,
        ):
            tools_layout.addWidget(row)
        layout.addWidget(tools_card)
        perf_card = QFrame()
        perf_card.setObjectName("Card")
        perf = QGridLayout(perf_card)
        perf.setContentsMargins(12, 12, 12, 12)
        self.language_combo = QComboBox()
        self.language_combo.addItem(_t("russian", self.language), "ru")
        self.language_combo.addItem(_t("english", self.language), "en")
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(self.language)))
        self.processes = QSpinBox()
        self.processes.setRange(1, 64)
        self.processes.setValue(int(values["max_processes"]))
        perf.addWidget(QLabel(_t("language", self.language)), 0, 0)
        perf.addWidget(QLabel(_t("max_processes", self.language)), 0, 1)
        perf.addWidget(self.language_combo, 1, 0)
        perf.addWidget(self.processes, 1, 1)
        layout.addWidget(perf_card)
        filters = QFrame()
        filters.setObjectName("Card")
        filters_layout = QVBoxLayout(filters)
        filters_layout.setContentsMargins(12, 12, 12, 12)
        filters_layout.addWidget(QLabel(_t("exclude_patterns", self.language)))
        self.exclude_edit = QPlainTextEdit(str(values["exclude_patterns"]))
        self.exclude_edit.setMinimumHeight(90)
        filters_layout.addWidget(self.exclude_edit)
        layout.addWidget(filters)
        preflight = QFrame()
        preflight.setObjectName("Card")
        preflight_layout = QGridLayout(preflight)
        preflight_layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel(_t("preflight_checks", self.language))
        heading.setObjectName("FieldLabel")
        preflight_layout.addWidget(heading, 0, 0, 1, 2)
        self.preflight_checks: dict[str, QCheckBox] = {}
        for index, (key, label) in enumerate(PREFLIGHT_LABELS.items()):
            checkbox = QCheckBox(label)
            checkbox.setChecked(bool(values["preflight_checks"].get(key, PREFLIGHT_CHECK_DEFAULTS[key])))
            preflight_layout.addWidget(checkbox, 1 + index // 2, index % 2)
            self.preflight_checks[key] = checkbox
        layout.addWidget(preflight)
        logs = QFrame()
        logs.setObjectName("Card")
        logs_layout = QGridLayout(logs)
        logs_layout.setContentsMargins(12, 12, 12, 12)
        logs_layout.addWidget(QLabel(_t("logs", self.language)), 0, 0, 1, 2)
        clear_button = QPushButton(_t("clear_logs", self.language))
        clear_button.clicked.connect(owner.clear_log_from_settings)
        open_button = QPushButton(_t("logs_folder", self.language))
        open_button.clicked.connect(owner.open_logs_folder)
        logs_layout.addWidget(clear_button, 1, 0)
        logs_layout.addWidget(open_button, 1, 1)
        layout.addWidget(logs)
        context_menu = QFrame()
        context_menu.setObjectName("Card")
        context_layout = QGridLayout(context_menu)
        context_layout.setContentsMargins(12, 12, 12, 12)
        context_layout.addWidget(QLabel(_t("context_menu", self.language)), 0, 0, 1, 2)
        self.context_menu_status = QLabel()
        self.context_menu_status.setWordWrap(True)
        context_layout.addWidget(self.context_menu_status, 1, 0, 1, 2)
        install_context = QPushButton(_t("install_context_menu", self.language))
        install_context.clicked.connect(lambda: owner.install_context_menu(self.context_menu_status))
        remove_context = QPushButton(_t("remove_context_menu", self.language))
        remove_context.clicked.connect(lambda: owner.remove_context_menu(self.context_menu_status))
        context_layout.addWidget(install_context, 2, 0)
        context_layout.addWidget(remove_context, 2, 1)
        owner.update_context_menu_status(self.context_menu_status)
        layout.addWidget(context_menu)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(_t("cancel", self.language))
        cancel.clicked.connect(self.reject)
        save = QPushButton(_t("save", self.language))
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def get_values(self) -> dict[str, Any]:
        return {
            "binarize_exe": self.binarize_row.text(),
            "cfgconvert_exe": self.cfgconvert_row.text(),
            "p3d_obfuscator_exe": self.obfuscator_row.text(),
            "dssignfile_exe": self.sign_row.text(),
            "private_key": self.key_row.text(),
            "project_root": self.project_row.text(),
            "temp_dir": self.temp_row.text(),
            "max_processes": self.processes.value(),
            "exclude_patterns": self.exclude_edit.toPlainText().strip(),
            "language": str(self.language_combo.currentData()),
            "preflight_checks": {key: checkbox.isChecked() for key, checkbox in self.preflight_checks.items()},
        }


class PboBuildWorker(QThread):
    log_line = Signal(str)
    progress_changed = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self, config: BuildConfig, targets: list[tuple[str, str]] | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.targets = targets
        self.lines: list[str] = []

    def _log(self, value: object) -> None:
        line = str(value)
        self.lines.append(line)
        self.log_line.emit(line)

    def _write_log(self) -> None:
        if not self.config.log_file:
            return
        try:
            path = Path(self.config.log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    def run(self) -> None:
        try:
            if self.targets is None:
                result: BuildResult | PreflightResult = build_all(self.config, self._log, self.progress_changed.emit)
            else:
                result = run_preflight_for_targets(self.config, self.targets, self._log, self.progress_changed.emit)
        except (BuildError, OSError, ValueError, RuntimeError) as exc:
            self._log(f"ERROR: {exc}")
            self._write_log()
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - граница фонового GUI worker
            message = f"{type(exc).__name__}: {exc}"
            self._log(f"ERROR: {message}")
            self._write_log()
            self.failed.emit(message)
        else:
            self._write_log()
            self.succeeded.emit(result)


class PboBuilderPage(QWidget):
    """Встроенная версия оригинального двухпанельного PBO Builder."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.current_language = _language(settings.language)
        self.worker: PboBuildWorker | None = None
        self.current_addon_targets: list[tuple[str, str]] = []
        self.log_lines: list[str] = []
        self.current_log_path = ""
        self.build_progress_dialog: BuildProgressDialog | None = None
        self.setObjectName("pboBuilderInterface")
        apply_pbo_style(self)
        self.advanced_settings = self._load_advanced_settings()
        self._build_ui()
        self._wire_events()
        self.refresh_addon_list()
        self.set_status(_t("ready", self.current_language), "ready")
        QTimer.singleShot(0, self.sync_addons_height)

    def _notify(self, kind: str, message: str, title: str = APP_TITLE) -> None:
        """Неблокирующее уведомление внутри общего окна RaiZo Tools."""
        method = {
            "success": InfoBar.success,
            "warning": InfoBar.warning,
            "error": InfoBar.error,
        }.get(kind, InfoBar.info)
        method(
            title=title,
            content=message,
            parent=self.window(),
            duration=6500 if kind == "error" else 4500,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("BuilderSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._create_left_panel())
        splitter.addWidget(self._create_addons_panel())
        splitter.setStretchFactor(0, 54)
        splitter.setStretchFactor(1, 46)
        splitter.setSizes([435, 375])
        root.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.setObjectName("BuilderProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        root.addWidget(self.progress)

    def _card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return card

    @staticmethod
    def _add_title(layout: QVBoxLayout | QGridLayout, title: str, *grid: int) -> None:
        label = QLabel(title)
        label.setObjectName("CardTitle")
        if isinstance(layout, QGridLayout):
            layout.addWidget(label, *grid)
        else:
            layout.addWidget(label)

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("LeftPanel")
        panel.setMinimumWidth(420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        paths = self._card()
        paths_layout = QVBoxLayout(paths)
        paths_layout.setContentsMargins(10, 8, 10, 8)
        paths_layout.setSpacing(3)
        self._add_title(paths_layout, _t("paths", self.current_language))
        status_row = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setObjectName("StatusDot")
        self.status_text = QLabel(_t("ready", self.current_language))
        self.status_text.setObjectName("StatusText")
        badge = QFrame()
        badge.setObjectName("StatusBadge")
        badge_layout = QHBoxLayout(badge)
        badge_layout.setContentsMargins(6, 2, 6, 2)
        badge_layout.setSpacing(5)
        badge_layout.addWidget(self.status_dot)
        badge_layout.addWidget(self.status_text)
        badge.setFixedWidth(116)
        status_row.addWidget(badge)
        status_row.addStretch(1)
        paths_layout.addLayout(status_row)
        self.source_root_row = SourceRootRow(
            _t("source_root", self.current_language),
            self.settings.pbo_last_source_root,
            self.settings.pbo_source_roots,
            language=self.current_language,
        )
        self.output_root_row = SourceRootRow(
            _t("output_root_client", self.current_language),
            self.settings.pbo_last_output_root,
            self.settings.pbo_output_roots,
            language=self.current_language,
        )
        self.output_root_server_row = SourceRootRow(
            _t("output_root_server", self.current_language),
            self.settings.pbo_last_output_server_root,
            self.settings.pbo_output_server_roots,
            language=self.current_language,
            empty_label=_t("same_as_client_output", self.current_language),
        )
        self.pbo_name_edit = QLineEdit(self.settings.pbo_last_name)
        self.pbo_name_edit.setPlaceholderText(_t("pbo_name_placeholder", self.current_language))
        self.pbo_name_edit.setFixedHeight(28)
        pbo_label = QLabel(_t("pbo_name", self.current_language))
        pbo_label.setObjectName("FieldLabel")
        paths_layout.addWidget(self.source_root_row)
        paths_layout.addWidget(self.output_root_row)
        paths_layout.addWidget(self.output_root_server_row)
        paths_layout.addWidget(pbo_label)
        paths_layout.addWidget(self.pbo_name_edit)
        layout.addWidget(paths)
        pipeline = self._card()
        pipeline_layout = QGridLayout(pipeline)
        pipeline_layout.setContentsMargins(10, 8, 10, 10)
        pipeline_layout.setHorizontalSpacing(8)
        pipeline_layout.setVerticalSpacing(5)
        self._add_title(pipeline_layout, _t("pipeline", self.current_language), 0, 0, 1, 2)
        self.use_binarize_check = QCheckBox(_t("binarize_p3d", self.current_language))
        self.protect_p3d_check = QCheckBox(_t("protect_p3d", self.current_language))
        self.convert_config_check = QCheckBox(_t("cpp_rvmat_to_bin", self.current_language))
        self.sign_pbos_check = QCheckBox(_t("sign_pbos", self.current_language))
        self.force_rebuild_check = QCheckBox(_t("force_rebuild", self.current_language))
        self.preflight_before_build_check = QCheckBox(_t("preflight_before_build", self.current_language))
        self.use_binarize_check.setChecked(self.settings.pack_use_binarize)
        self.protect_p3d_check.setChecked(self.settings.pack_protect_p3d)
        self.convert_config_check.setChecked(self.settings.pack_convert_config)
        self.sign_pbos_check.setChecked(self.settings.pack_sign_pbos)
        self.force_rebuild_check.setChecked(self.settings.pack_engine == "full")
        self.preflight_before_build_check.setChecked(self.settings.pack_preflight)
        pipeline_layout.addWidget(self.use_binarize_check, 1, 0)
        pipeline_layout.addWidget(self.convert_config_check, 1, 1)
        pipeline_layout.addWidget(self.protect_p3d_check, 2, 0)
        pipeline_layout.addWidget(self.force_rebuild_check, 2, 1)
        pipeline_layout.addWidget(self.sign_pbos_check, 3, 0)
        pipeline_layout.addWidget(self.preflight_before_build_check, 4, 0)
        layout.addWidget(pipeline)
        actions = self._card()
        self.action_card = actions
        actions_layout = QGridLayout(actions)
        actions_layout.setContentsMargins(10, 8, 10, 10)
        actions_layout.setSpacing(6)
        self._add_title(actions_layout, _t("actions", self.current_language), 0, 0, 1, 3)
        self.build_button = QPushButton(_t("build_pbos", self.current_language))
        self.build_button.setObjectName("PrimaryButton")
        self.preflight_button = QPushButton(_t("preflight", self.current_language))
        self.clear_all_temp_button = QPushButton(_t("clear_all_temp", self.current_language))
        self.clear_cache_button = QPushButton(_t("clear_cache", self.current_language))
        self.latest_log_button = QPushButton(_t("latest_log", self.current_language))
        actions_layout.addWidget(self.build_button, 1, 0, 1, 2)
        actions_layout.addWidget(self.preflight_button, 1, 2)
        actions_layout.addWidget(self.clear_all_temp_button, 2, 0)
        actions_layout.addWidget(self.clear_cache_button, 2, 1)
        actions_layout.addWidget(self.latest_log_button, 2, 2)
        layout.addWidget(actions)
        layout.addStretch(1)
        return panel

    def _create_addons_panel(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("AddonsWrapper")
        wrapper.setMinimumWidth(350)
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(8, 0, 0, 0)
        wrapper_layout.setSpacing(0)
        card = self._card()
        self.addons_card = card
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        self._add_title(layout, _t("addons", self.current_language))
        self.addon_list = QListWidget()
        self.addon_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.addon_list, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.refresh_button = QPushButton(_t("refresh", self.current_language))
        self.select_all_button = QPushButton(_t("all", self.current_language))
        self.select_none_button = QPushButton(_t("none", self.current_language))
        self.settings_button = QToolButton()
        self.settings_button.setObjectName("AddonIconButton")
        self.settings_button.setFixedSize(36, 36)
        _set_button_icon(
            self.settings_button,
            "options.png",
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            17,
        )
        self.settings_button.setToolTip(_t("settings", self.current_language))
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.select_all_button)
        buttons.addWidget(self.select_none_button)
        buttons.addWidget(self.settings_button)
        layout.addLayout(buttons)
        wrapper_layout.addWidget(card)
        wrapper_layout.addStretch(1)
        return wrapper

    def _wire_events(self) -> None:
        self.source_root_row.changed.connect(self.refresh_addon_list)
        self.output_root_row.changed.connect(self.refresh_addon_list)
        self.output_root_server_row.changed.connect(self.save_settings)
        self.refresh_button.clicked.connect(self.refresh_addon_list)
        self.select_all_button.clicked.connect(self.select_all_addons)
        self.select_none_button.clicked.connect(self.select_no_addons)
        self.addon_list.itemChanged.connect(self.save_settings)
        self.build_button.clicked.connect(self.start_build)
        self.preflight_button.clicked.connect(self.start_preflight)
        self.clear_all_temp_button.clicked.connect(self.clear_full_temp_from_ui)
        self.clear_cache_button.clicked.connect(self.clear_build_cache_from_ui)
        self.latest_log_button.clicked.connect(self.open_latest_log)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.pbo_name_edit.textChanged.connect(self.save_settings)
        for checkbox in (
            self.use_binarize_check,
            self.protect_p3d_check,
            self.convert_config_check,
            self.sign_pbos_check,
            self.force_rebuild_check,
            self.preflight_before_build_check,
        ):
            checkbox.toggled.connect(self.save_settings)

    def _load_advanced_settings(self) -> dict[str, Any]:
        detected = packer.build_config(self.settings, Path.cwd(), Path.cwd(), ())
        checks = dict(PREFLIGHT_CHECK_DEFAULTS)
        checks.update(self.settings.pack_preflight_checks)
        return {
            "binarize_exe": self.settings.pack_binarize_exe or detected.binarize_exe,
            "cfgconvert_exe": self.settings.pack_cfgconvert_exe or detected.cfgconvert_exe,
            "p3d_obfuscator_exe": self.settings.pack_p3d_obfuscator_exe,
            "dssignfile_exe": self.settings.pack_dssignfile_exe or detected.dssignfile_exe,
            "private_key": self.settings.pack_private_key,
            "project_root": self.settings.pbo_last_project_root or DEFAULT_PROJECT_ROOT,
            "temp_dir": self.settings.pack_temp_dir or str(get_app_data_dir() / "temp"),
            "max_processes": self.settings.pack_max_processes or get_default_max_processes(),
            "exclude_patterns": self.settings.pack_exclude_patterns or DEFAULT_EXCLUDE_PATTERNS,
            "preflight_checks": checks,
        }

    def save_settings(self) -> None:
        self.settings.pbo_last_source_root = self.source_root_row.text()
        self.settings.pbo_source_roots = self.source_root_row.source_roots()
        self.settings.pbo_last_output_root = self.output_root_row.text()
        self.settings.pbo_output_roots = self.output_root_row.source_roots()
        self.settings.pbo_last_output_server_root = self.output_root_server_row.text()
        self.settings.pbo_output_server_roots = self.output_root_server_row.source_roots()
        self.settings.pbo_last_name = self.pbo_name_edit.text().strip()
        self.settings.pack_use_binarize = self.use_binarize_check.isChecked()
        self.settings.pack_protect_p3d = self.protect_p3d_check.isChecked()
        self.settings.pack_convert_config = self.convert_config_check.isChecked()
        self.settings.pack_sign_pbos = self.sign_pbos_check.isChecked()
        self.settings.pack_engine = "full" if self.force_rebuild_check.isChecked() else "normal"
        self.settings.pack_preflight = self.preflight_before_build_check.isChecked()
        self.settings.save()

    def refresh_addon_list(self) -> None:
        previous = set(self.get_selected_addon_names())
        self.addon_list.blockSignals(True)
        self.addon_list.clear()
        self.current_addon_targets = []
        source = self.source_root_row.text()
        output = self.output_root_row.text()
        if source and Path(source).is_dir():
            try:
                self.current_addon_targets = detect_addon_targets(
                    source, str(Path(output) / "Addons") if output else ""
                )
            except OSError:
                self.current_addon_targets = []
        for name, _path in self.current_addon_targets:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in previous else Qt.CheckState.Unchecked)
            self.addon_list.addItem(item)
        self.addon_list.blockSignals(False)

    def get_selected_addon_names(self) -> list[str]:
        return [
            self.addon_list.item(index).text()
            for index in range(self.addon_list.count())
            if self.addon_list.item(index).checkState() == Qt.CheckState.Checked
        ]

    def select_all_addons(self) -> None:
        for index in range(self.addon_list.count()):
            self.addon_list.item(index).setCheckState(Qt.CheckState.Checked)

    def select_no_addons(self) -> None:
        for index in range(self.addon_list.count()):
            self.addon_list.item(index).setCheckState(Qt.CheckState.Unchecked)

    @staticmethod
    def _inside(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
        except ValueError:
            return False
        return True

    def _require_file(self, value: str, label: str) -> None:
        if not value:
            raise BuildError(_t("select_required", self.current_language, label=label))
        if not Path(value).is_file():
            raise BuildError(_t("file_missing", self.current_language, label=label, path=value))

    def _config(self, *, preflight_only: bool = False) -> BuildConfig:
        source_text = self.source_root_row.text()
        if not source_text:
            raise BuildError(_t("select_source_root", self.current_language))
        source = Path(source_text).resolve()
        if not source.is_dir():
            raise BuildError(_t("source_root_missing", self.current_language, path=source))
        selected = tuple(self.get_selected_addon_names())
        if not selected:
            key = "select_addon_check" if preflight_only else "select_addon_build"
            raise BuildError(_t(key, self.current_language))
        output_text = self.output_root_row.text()
        if not preflight_only and not output_text:
            raise BuildError(_t("select_output_client", self.current_language))
        output = Path(output_text).resolve() if output_text else source.parent
        server_text = self.output_root_server_row.text()
        server_output = Path(server_text).resolve() if server_text else output
        if not preflight_only and (
            output == source
            or self._inside(output, source)
            or server_output == source
            or self._inside(server_output, source)
        ):
            raise BuildError(_t("output_inside", self.current_language))
        pbo_name = self.pbo_name_edit.text().strip()
        if pbo_name and len(selected) != 1:
            raise BuildError(_t("pbo_override_single", self.current_language))
        if not preflight_only:
            if self.use_binarize_check.isChecked():
                self._require_file(str(self.advanced_settings["binarize_exe"]), "binarize.exe")
            if self.protect_p3d_check.isChecked():
                if not self.use_binarize_check.isChecked():
                    raise BuildError(_t("protect_requires_binarize", self.current_language))
                self._require_file(str(self.advanced_settings["p3d_obfuscator_exe"]), "P3DObfuscator.exe")
            if self.convert_config_check.isChecked():
                self._require_file(str(self.advanced_settings["cfgconvert_exe"]), "CfgConvert.exe")
            if self.sign_pbos_check.isChecked() and any(not name.upper().endswith("_SERVER") for name in selected):
                self._require_file(str(self.advanced_settings["dssignfile_exe"]), "DSSignFile.exe")
                self._require_file(str(self.advanced_settings["private_key"]), _t("private_key", self.current_language))
        self._apply_advanced_settings()
        self.save_settings()
        self.current_log_path = str(create_build_log_path())
        config = packer.build_config(
            self.settings,
            source,
            output,
            selected,
            output_server_root=server_output,
            project_root=str(self.advanced_settings["project_root"]),
            pbo_name=pbo_name,
            force_rebuild=self.force_rebuild_check.isChecked(),
            log_file=self.current_log_path,
        )
        if preflight_only:
            config = replace(config, preflight_before_build=False)
        return config

    def _apply_advanced_settings(self) -> None:
        self.settings.pack_binarize_exe = str(self.advanced_settings["binarize_exe"])
        self.settings.pack_cfgconvert_exe = str(self.advanced_settings["cfgconvert_exe"])
        self.settings.pack_p3d_obfuscator_exe = str(self.advanced_settings["p3d_obfuscator_exe"])
        self.settings.pack_dssignfile_exe = str(self.advanced_settings["dssignfile_exe"])
        self.settings.pack_private_key = str(self.advanced_settings["private_key"])
        self.settings.pbo_last_project_root = str(self.advanced_settings["project_root"])
        self.settings.pack_temp_dir = str(self.advanced_settings["temp_dir"])
        self.settings.pack_max_processes = int(self.advanced_settings["max_processes"])
        self.settings.pack_exclude_patterns = str(self.advanced_settings["exclude_patterns"])
        self.settings.pack_preflight_checks = dict(self.advanced_settings["preflight_checks"])

    def _selected_targets(self) -> list[tuple[str, str]]:
        selected = set(self.get_selected_addon_names())
        return [(name, path) for name, path in self.current_addon_targets if name in selected]

    def start_build(self) -> None:
        if self.is_busy():
            return
        try:
            config = self._config()
        except (BuildError, OSError, ValueError) as exc:
            self._notify("warning", str(exc))
            return
        self.log_lines.clear()
        self._set_running(True, _t("build_running_status", self.current_language), "building")
        self.worker = PboBuildWorker(config, parent=self)
        self._connect_worker()
        self.worker.start()
        self.build_progress_dialog = BuildProgressDialog(self, self.current_language)
        self.build_progress_dialog.show()

    def start_preflight(self) -> None:
        if self.is_busy():
            return
        try:
            config = self._config(preflight_only=True)
            targets = self._selected_targets()
        except (BuildError, OSError, ValueError) as exc:
            self._notify("warning", str(exc))
            return
        self.log_lines.clear()
        self._set_running(True, _t("preflight_running_status", self.current_language), "preflight")
        self.worker = PboBuildWorker(config, targets, self)
        self._connect_worker()
        self.worker.start()

    def _connect_worker(self) -> None:
        assert self.worker is not None
        self.worker.log_line.connect(self.log_lines.append)
        self.worker.progress_changed.connect(self.on_progress)
        self.worker.succeeded.connect(self.on_worker_succeeded)
        self.worker.failed.connect(self.on_worker_failed)

    def _set_running(self, running: bool, status: str, kind: str) -> None:
        self.build_button.setEnabled(not running)
        self.preflight_button.setEnabled(not running)
        self.progress.setValue(0)
        self.set_status(status, kind)

    def on_progress(self, current: int, total: int) -> None:
        maximum = max(total, 1)
        self.progress.setRange(0, maximum)
        self.progress.setValue(min(current, maximum))
        self.set_status(_t("working_status", self.current_language, current=current, maximum=maximum), "building")

    def on_worker_succeeded(self, result: object) -> None:
        self._close_progress_dialog()
        if isinstance(result, PreflightResult):
            self._set_running(False, _t("preflight_finished_status", self.current_language), "success")
            self.progress.setValue(self.progress.maximum())
            if result.errors:
                message = _t("preflight_errors", self.current_language, errors=result.errors, warnings=result.warnings)
                self.show_log_dialog(_t("preflight_log", self.current_language), message)
                self._notify("error", message)
            elif result.warnings:
                self._notify(
                    "warning",
                    _t("preflight_warnings", self.current_language, warnings=result.warnings),
                )
            else:
                self._notify("success", _t("preflight_ok", self.current_language))
        else:
            self._set_running(False, _t("build_finished_status", self.current_language), "success")
            self.progress.setValue(self.progress.maximum())
            self._notify("success", _t("build_finished_message", self.current_language))

    def on_worker_failed(self, message: str) -> None:
        self._close_progress_dialog()
        self._set_running(False, _t("error_status", self.current_language), "error")
        self.show_log_dialog(_t("build_log", self.current_language), message)
        self._notify("error", message)

    def _close_progress_dialog(self) -> None:
        if self.build_progress_dialog is not None:
            self.build_progress_dialog.finish()
            self.build_progress_dialog.deleteLater()
            self.build_progress_dialog = None

    def set_status(self, text: str, kind: str) -> None:
        colors = {
            "ready": BRAND_SUCCESS,
            "building": BRAND_WARNING,
            "preflight": BRAND_INFO,
            "success": BRAND_SUCCESS,
            "error": BRAND_ERROR,
        }
        color = colors.get(kind, colors["ready"])
        self.status_text.setText(text)
        self.status_dot.setStyleSheet(
            f"background:{color}; border-radius:4px; min-width:8px; max-width:8px; min-height:16px; max-height:16px;"
        )

    def open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.advanced_settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        previous_language = self.current_language
        self.advanced_settings.update(dialog.get_values())
        self.current_language = _language(str(self.advanced_settings.pop("language")))
        self.settings.language = self.current_language
        self._apply_advanced_settings()
        self.settings.save()
        if previous_language != self.current_language:
            self._notify("info", _t("language_restart", self.current_language))

    def update_context_menu_status(self, label: QLabel) -> None:
        key = "context_menu_installed" if pbo_context_menu.is_installed() else "context_menu_not_installed"
        label.setText(_t(key, self.current_language))

    def install_context_menu(self, label: QLabel) -> None:
        self.save_settings()
        try:
            pbo_context_menu.install()
        except OSError as exc:
            _show_message(
                self,
                _t("context_menu_error", self.current_language, error=exc),
                self.current_language,
            )
        self.update_context_menu_status(label)

    def remove_context_menu(self, label: QLabel) -> None:
        try:
            pbo_context_menu.remove()
        except OSError as exc:
            _show_message(
                self,
                _t("context_menu_error", self.current_language, error=exc),
                self.current_language,
            )
        self.update_context_menu_status(label)

    @staticmethod
    def _log_color(line: str) -> str:
        upper = line.strip().upper()
        if upper.startswith("ERROR") or " ERROR:" in upper:
            return BRAND_ERROR
        if upper.startswith("WARNING") or " WARNING:" in upper:
            return BRAND_WARNING
        if "BUILD FINISHED" in upper or upper.endswith(" OK"):
            return BRAND_SUCCESS
        if "BINARIZE" in upper or "CFGCONVERT" in upper or "PREFLIGHT" in upper:
            return BRAND_INFO
        return ""

    def show_log_dialog(self, title: str, message: str = "") -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        apply_pbo_style(dialog)
        dialog.resize(720, 520)
        dialog.setMinimumSize(620, 420)
        layout = QVBoxLayout(dialog)
        heading = QLabel(message or title)
        heading.setObjectName("DialogTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 9))
        text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        for line in self.log_lines:
            color = self._log_color(line)
            escaped = html.escape(line)
            text.append(f'<span style="color:{color}">{escaped}</span>' if color else escaped)
        text.moveCursor(QTextCursor.MoveOperation.End)
        layout.addWidget(text, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if self.current_log_path:
            open_button = QPushButton(_t("open_file", self.current_language))
            open_button.clicked.connect(lambda: _open_path(self, self.current_log_path))
            buttons.addWidget(open_button)
        close_button = QPushButton(_t("close", self.current_language))
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(dialog.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        dialog.exec()

    def clear_log_from_settings(self) -> None:
        if self.is_busy():
            _show_message(self, _t("cannot_clear_logs", self.current_language), self.current_language)
            return
        files = [path for path in get_logs_dir().iterdir() if path.is_file()]
        deleted = 0
        for path in files:
            try:
                path.unlink()
                deleted += 1
            except OSError:
                continue
        message = (
            _t("logs_cleared", self.current_language, count=deleted)
            if files
            else _t("logs_empty", self.current_language)
        )
        _show_message(self, message, self.current_language)

    def clear_full_temp_from_ui(self) -> None:
        if self.is_busy():
            self._notify("warning", _t("cannot_clear_all_temp", self.current_language))
            return
        temp = str(self.advanced_settings["temp_dir"] or DEFAULT_TEMP_DIR)
        if not _confirm(
            self,
            _t("clear_all_temp_title", self.current_language),
            _t("clear_all_temp_confirm", self.current_language, path=temp),
            _t("clear_all_temp_action", self.current_language),
            self.current_language,
        ):
            return
        try:
            clear_full_temp_folder(
                temp, self.log_lines.append, self.source_root_row.text(), self.output_root_row.text()
            )
        except (BuildError, OSError) as exc:
            self._notify("error", str(exc))
        else:
            self._notify("success", _t("all_temp_cleared", self.current_language))

    def clear_build_cache_from_ui(self) -> None:
        if self.is_busy():
            self._notify("warning", _t("cannot_clear_cache", self.current_language))
            return
        selected = self.get_selected_addon_names()
        source = self.source_root_row.text()
        if not selected:
            self._notify("warning", _t("select_addon", self.current_language))
            return
        if not _confirm(
            self,
            _t("clear_cache_title", self.current_language),
            _t("clear_cache_confirm", self.current_language),
            _t("clear_cache_action", self.current_language),
            self.current_language,
        ):
            return
        cache = load_build_cache()
        root_key = os.path.abspath(source).lower()
        source_cache = cache.get(root_key, {})
        cleared = 0
        for addon in selected:
            if addon in source_cache:
                del source_cache[addon]
                cleared += 1
        if source_cache:
            cache[root_key] = source_cache
        else:
            cache.pop(root_key, None)
        save_build_cache(cache)
        self._notify("success", _t("cache_cleared", self.current_language, count=cleared))

    def open_logs_folder(self) -> None:
        _open_path(self, str(get_logs_dir()))

    def open_latest_log(self) -> None:
        logs = list(get_logs_dir().glob("build_*.log"))
        if not logs:
            self._notify("info", _t("no_build_logs", self.current_language))
            return
        _open_path(self, str(max(logs, key=lambda path: path.stat().st_mtime)))

    def sync_addons_height(self) -> None:
        action_bottom = self.action_card.mapTo(self, self.action_card.rect().bottomLeft()).y()
        addons_top = self.addons_card.mapTo(self, self.addons_card.rect().topLeft()).y()
        height = max(260, action_bottom - addons_top + 1)
        self.addons_card.setFixedHeight(height)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self.sync_addons_height)

    def is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()
