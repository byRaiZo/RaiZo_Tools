"""Настройки встроенного PBO Builder byRaiZo."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
)

from core.settings import Settings
from ui.theme import ThemedDialog


class PboProjectDialog(ThemedDialog):
    """Компактный редактор параметров собственного backend."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("PBO Builder byRaiZo")
        self.resize(700, 520)

        root = QVBoxLayout(self)
        intro = CaptionLabel(
            "Встроенный packer: preflight, incremental cache, P3D Binarize, "
            "CfgConvert, подпись и безопасная публикация с rollback."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        self.use_binarize = CheckBox("Binarize P3D и texHeaders")
        self.use_binarize.setChecked(settings.pack_use_binarize)
        form.addRow("", self.use_binarize)

        self.convert_config = CheckBox("CfgConvert: config.cpp/RVMAT")
        self.convert_config.setChecked(settings.pack_convert_config)
        form.addRow("", self.convert_config)

        self.preflight = CheckBox("Preflight перед сборкой")
        self.preflight.setChecked(settings.pack_preflight)
        form.addRow("", self.preflight)

        self.sign = CheckBox("Подписывать клиентские PBO")
        self.sign.setChecked(settings.pack_sign_pbos)
        form.addRow("", self.sign)

        key_row = QHBoxLayout()
        self.private_key = LineEdit()
        self.private_key.setText(settings.pack_private_key)
        key_button = PushButton("Обзор…")
        key_button.clicked.connect(self._browse_key)
        key_row.addWidget(self.private_key, 1)
        key_row.addWidget(key_button)
        form.addRow(BodyLabel("Приватный ключ"), key_row)

        self.processes = SpinBox()
        self.processes.setRange(0, 64)
        self.processes.setValue(settings.pack_max_processes)
        self.processes.setToolTip("0 — использовать все доступные логические потоки")
        form.addRow(BodyLabel("Параллельные процессы"), self.processes)

        self.exclude = PlainTextEdit()
        self.exclude.setPlainText(settings.pack_exclude_patterns)
        self.exclude.setMinimumHeight(110)
        form.addRow(BodyLabel("Исключения"), self.exclude)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = PushButton("Отмена")
        save = PrimaryPushButton("Сохранить")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите .biprivatekey",
            self.private_key.text(),
            "DayZ private key (*.biprivatekey);;Все файлы (*)",
        )
        if path:
            self.private_key.setText(path)

    def _save(self) -> None:
        self.settings.pack_use_binarize = self.use_binarize.isChecked()
        self.settings.pack_convert_config = self.convert_config.isChecked()
        self.settings.pack_preflight = self.preflight.isChecked()
        self.settings.pack_sign_pbos = self.sign.isChecked()
        self.settings.pack_private_key = self.private_key.text().strip()
        self.settings.pack_max_processes = self.processes.value()
        self.settings.pack_exclude_patterns = self.exclude.toPlainText().strip()
        self.settings.save()
        self.accept()

    # Совместимость с прежними двумя вызывающими местами.
    def result_flags(self) -> str:
        return self.settings.pack_flags

    def result_clean_meta(self) -> bool:
        return False
