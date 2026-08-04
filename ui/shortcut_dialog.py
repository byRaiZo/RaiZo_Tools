"""Диалог создания ярлыка запуска/остановки выбранного пресета."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout
from qfluentwidgets import ComboBox, LineEdit, PrimaryPushButton, PushButton, SubtitleLabel

from core.i18n import tr
from core.shortcuts import default_desktop


class ShortcutDialog(QDialog):
    def __init__(self, preset_name: str, parent=None) -> None:
        super().__init__(parent)
        self.preset_name = preset_name
        self.setWindowTitle(tr("shortcut.title", "Создать ярлык"))
        self.setMinimumWidth(540)

        root = QVBoxLayout(self)
        root.addWidget(SubtitleLabel(tr("shortcut.heading", "Ярлык управления пресетом")))
        form = QFormLayout()
        self.action_combo = ComboBox()
        self.action_combo.addItem(tr("shortcut.start", "Запустить"), userData="start")
        self.action_combo.addItem(tr("shortcut.stop", "Остановить"), userData="stop")
        form.addRow(tr("shortcut.action", "Действие"), self.action_combo)

        self.target_combo = ComboBox()
        self.target_combo.addItem(tr("shortcut.all", "Сервер и клиент"), userData="all")
        self.target_combo.addItem(tr("shortcut.server", "Только сервер"), userData="server")
        self.target_combo.addItem(tr("shortcut.client", "Только клиент"), userData="client")
        form.addRow(tr("shortcut.target", "Что выполнить"), self.target_combo)

        file_row = QHBoxLayout()
        self.path_edit = LineEdit()
        self.path_edit.setText(str(default_desktop() / self._default_name()))
        browse = PushButton(tr("shortcut.browse", "Обзор…"))
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)
        form.addRow(tr("shortcut.file", "Файл ярлыка"), file_row)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = PushButton(tr("common.cancel", "Отмена"))
        create = PrimaryPushButton(tr("shortcut.create", "Создать"))
        cancel.clicked.connect(self.reject)
        create.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        root.addLayout(buttons)

    def _default_name(self) -> str:
        return f"RaiZo Tools - {self.preset_name}.lnk"

    def _browse(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            tr("shortcut.title", "Создать ярлык"),
            self.path_edit.text(),
            tr("shortcut.filter", "Ярлык Windows (*.lnk)"),
        )
        if selected:
            self.path_edit.setText(selected)

    def values(self) -> tuple[Path, str, str]:
        return (
            Path(self.path_edit.text().strip()).with_suffix(".lnk"),
            str(self.action_combo.currentData()),
            str(self.target_combo.currentData()),
        )
