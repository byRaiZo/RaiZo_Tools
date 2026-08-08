"""Общие параметры сборки PBO для ручной и автоматической упаковки."""

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

from core.i18n import tr
from core.settings import Settings
from ui.theme import ThemedDialog


class PboProjectDialog(ThemedDialog):
    """Общий пайплайн вкладки PBO Builder и перепаковки перед запуском."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("repack_settings.title", "Общие параметры сборки PBO"))
        self.resize(700, 520)

        root = QVBoxLayout(self)
        self.intro = CaptionLabel(
            tr(
                "repack_settings.intro",
                "Эти параметры общие для автоперепаковки модов перед запуском и отдельной вкладки «PBO Builder».",
            )
        )
        self.intro.setWordWrap(True)
        root.addWidget(self.intro)

        form = QFormLayout()
        self.use_binarize = CheckBox(tr("repack_settings.binarize", "Бинаризовать модели P3D и texHeaders (Binarize)"))
        self.use_binarize.setToolTip(
            tr(
                "repack_settings.binarize_tip",
                "Преобразует исходные модели в игровой формат. Требуется binarize.exe из DayZ Tools.",
            )
        )
        self.use_binarize.setChecked(settings.pack_use_binarize)
        form.addRow("", self.use_binarize)

        self.convert_config = CheckBox(
            tr("repack_settings.convert", "Преобразовать config.cpp и RVMAT в BIN (CfgConvert)")
        )
        self.convert_config.setToolTip(
            tr(
                "repack_settings.convert_tip",
                "Создаёт бинарные config.bin и RVMAT через CfgConvert из DayZ Tools.",
            )
        )
        self.convert_config.setChecked(settings.pack_convert_config)
        form.addRow("", self.convert_config)

        self.preflight = CheckBox(tr("repack_settings.preflight", "Проверять мод перед сборкой (Preflight)"))
        self.preflight.setToolTip(
            tr(
                "repack_settings.preflight_tip",
                "Проверяет конфиги, структуру аддона, P3D и ссылки до создания PBO.",
            )
        )
        self.preflight.setChecked(settings.pack_preflight)
        form.addRow("", self.preflight)

        self.sign = CheckBox(tr("repack_settings.sign", "Подписывать собранные PBO"))
        self.sign.setToolTip(
            tr(
                "repack_settings.sign_tip",
                "Создаёт .bisign через DSSignFile. Нужен приватный ключ ниже.",
            )
        )
        self.sign.setChecked(settings.pack_sign_pbos)
        form.addRow("", self.sign)

        key_row = QHBoxLayout()
        self.private_key = LineEdit()
        self.private_key.setText(settings.pack_private_key)
        self.private_key.setPlaceholderText(tr("repack_settings.key_placeholder", "Путь к файлу .biprivatekey"))
        self.private_key.setToolTip(
            tr(
                "repack_settings.key_tip",
                "Ключ используется только локально для подписи и не копируется в релиз RaiZo Tools.",
            )
        )
        key_button = PushButton(tr("repack_settings.browse", "Выбрать…"))
        key_button.clicked.connect(self._browse_key)
        key_row.addWidget(self.private_key, 1)
        key_row.addWidget(key_button)
        form.addRow(BodyLabel(tr("repack_settings.key", "Ключ подписи (.biprivatekey)")), key_row)

        self.processes = SpinBox()
        self.processes.setRange(0, 64)
        self.processes.setValue(settings.pack_max_processes)
        self.processes.setToolTip(
            tr(
                "repack_settings.processes_tip",
                "Сколько операций выполнять одновременно. 0 — определить автоматически по процессору.",
            )
        )
        form.addRow(BodyLabel(tr("repack_settings.processes", "Одновременные операции")), self.processes)

        self.exclude = PlainTextEdit()
        self.exclude.setPlainText(settings.pack_exclude_patterns)
        self.exclude.setPlaceholderText(tr("repack_settings.exclude_placeholder", "Например: *.psd, *.bak, source"))
        self.exclude.setToolTip(
            tr(
                "repack_settings.exclude_tip",
                "Маски файлов и папок, которые не попадут в PBO. "
                "Разделители: запятая, точка с запятой или новая строка.",
            )
        )
        self.exclude.setMinimumHeight(110)
        form.addRow(BodyLabel(tr("repack_settings.exclude", "Не включать в PBO")), self.exclude)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = PushButton(tr("common.cancel", "Отмена"))
        save = PrimaryPushButton(tr("common.save", "Сохранить"))
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("repack_settings.key_dialog", "Выберите приватный ключ DayZ"),
            self.private_key.text(),
            tr(
                "repack_settings.key_filter",
                "Приватный ключ DayZ (*.biprivatekey);;Все файлы (*)",
            ),
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
