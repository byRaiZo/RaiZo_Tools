from PySide6.QtWidgets import QLabel

from core import i18n
from core.settings import Settings
from ui.pboproject_dialog import PboProjectDialog


def test_repack_settings_explain_shared_scope(qtbot, monkeypatch):
    i18n.load("ru")
    settings = Settings(pack_use_binarize=True)
    monkeypatch.setattr(Settings, "save", lambda self: None)
    dialog = PboProjectDialog(settings)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Общие параметры сборки PBO"
    assert "автоперепаковки" in dialog.intro.text()
    assert "вкладки «PBO Builder»" in dialog.intro.text()
    assert dialog.use_binarize.text() == "Бинаризовать модели P3D и texHeaders (Binarize)"
    assert dialog.convert_config.text() == "Преобразовать config.cpp и RVMAT в BIN (CfgConvert)"
    assert dialog.preflight.text() == "Проверять мод перед сборкой (Preflight)"
    assert dialog.sign.text() == "Подписывать собранные PBO"
    labels = {label.text() for label in dialog.findChildren(QLabel)}
    assert "Ключ подписи (.biprivatekey)" in labels
    assert "Одновременные операции" in labels
    assert "Не включать в PBO" in labels


def test_repack_dialog_saves_shared_builder_options(qtbot, monkeypatch):
    i18n.load("ru")
    settings = Settings(pack_use_binarize=True, pack_preflight=True)
    monkeypatch.setattr(Settings, "save", lambda self: None)
    dialog = PboProjectDialog(settings)
    qtbot.addWidget(dialog)
    dialog.use_binarize.setChecked(False)
    dialog.preflight.setChecked(False)

    dialog._save()

    assert settings.pack_use_binarize is False
    assert settings.pack_preflight is False
