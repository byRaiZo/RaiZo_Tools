from typing import cast

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from qfluentwidgets import ComboBox

from core.params import CLIENT, SERVER
from core.presets import MODE_DEDICATED, MODE_DIAG, ServerPreset
from core.settings import Settings
from ui.mission_picker import MapPicker
from ui.preset_editor import AdvancedPresetDialog, LazyPresetWizard


def _send_wheel(widget: QWidget) -> None:
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_advanced_preset_editor_remains_usable_at_small_height(qtbot):
    dialog = AdvancedPresetDialog(ServerPreset(name="Diag"), Settings())
    qtbot.addWidget(dialog)
    dialog.resize(620, 460)
    dialog.show()
    qtbot.wait(10)

    scroll = dialog.findChild(QScrollArea, "presetScrollArea")
    save = dialog.findChild(QWidget, "presetSaveButton")

    assert scroll is not None
    assert save is not None
    assert scroll.verticalScrollBar().maximum() > 0
    assert save.isVisible()
    assert not scroll.isAncestorOf(save)

    port = dialog.port.value()
    time_login = dialog.time_login.value()
    _send_wheel(dialog.port)
    _send_wheel(dialog.time_login)
    assert dialog.port.value() == port
    assert dialog.time_login.value() == time_login


def test_selecting_diag_enables_debug_defaults(qtbot, tmp_path):
    client = tmp_path / "DayZ"
    server = tmp_path / "DayZServer"
    client.mkdir()
    server.mkdir()
    (client / "DayZDiag_x64.exe").touch()
    (server / "DayZServer_x64.exe").touch()
    settings = Settings(client_stable=str(client), server_stable=str(server))
    preset = ServerPreset(name="Dedicated", mode=MODE_DEDICATED)

    dialog = AdvancedPresetDialog(preset, settings)
    qtbot.addWidget(dialog)
    assert dialog.mode.currentData() == MODE_DEDICATED

    dialog.mode.setCurrentIndex(0)
    qtbot.wait(10)

    assert dialog.mode.currentData() == MODE_DIAG
    for target in (SERVER, CLIENT):
        file_patching = cast(ComboBox, dialog._param_widgets[(target, "filePatching")])
        battleye = cast(ComboBox, dialog._param_widgets[(target, "battleye")])
        new_errors = cast(ComboBox, dialog._param_widgets[(target, "newErrorsAreWarnings")])
        assert file_patching.currentData() is True
        assert battleye.currentData() is False
        assert new_errors.currentData() is True

    dialog.mode.setCurrentIndex(1)
    qtbot.wait(10)

    assert dialog.mode.currentData() == MODE_DEDICATED
    for target in (SERVER, CLIENT):
        assert (target, "filePatching") not in dialog._param_widgets


def test_wizard_reuses_existing_mission_and_cfg(qtbot, tmp_path, monkeypatch):
    import core.presets as presets_module

    client = tmp_path / "DayZ"
    server = tmp_path / "DayZServer"
    mission = server / "mpmissions" / "Shared.chernarusplus"
    client.mkdir()
    mission.mkdir(parents=True)
    (client / "DayZDiag_x64.exe").touch()
    (server / "DayZServer_x64.exe").touch()
    (server / "serverDZ.cfg").write_text("shared", encoding="utf-8")
    monkeypatch.setattr(presets_module, "PRESETS_DIR", tmp_path / "presets")
    settings = Settings(client_stable=str(client), server_stable=str(server))

    picker = MapPicker()
    qtbot.addWidget(picker)
    picker.set_context(settings, "stable", MODE_DIAG, "SharedPreset")
    assert picker.mission_name() == "Shared.chernarusplus"

    wizard = LazyPresetWizard(settings)
    qtbot.addWidget(wizard)
    wizard.name.setText("SharedPreset")
    wizard._sync_map_ctx()
    assert wizard.map_picker.mission_name() == "Shared.chernarusplus"
    assert wizard.cfg_picker.config_name() == "serverDZ.cfg"
    assert not wizard.cfg_picker.needs_creation()

    wizard.accept()

    assert wizard.result_preset is not None
    assert wizard.result_preset.mission == "Shared.chernarusplus"
    assert wizard.result_preset.server_config == "serverDZ.cfg"
    assert not (server / "serverDZ_SharedPreset_chernarusplus.cfg").exists()

    editor = AdvancedPresetDialog(wizard.result_preset, settings)
    qtbot.addWidget(editor)
    assert editor.map_picker.mission_name() == "Shared.chernarusplus"
    assert editor.cfg_picker.config_name() == "serverDZ.cfg"
    editor._save()
    assert wizard.result_preset.server_config == "serverDZ.cfg"
    assert not (server / "serverDZ_SharedPreset_chernarusplus.cfg").exists()
