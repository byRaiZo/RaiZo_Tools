from pathlib import Path

from PySide6.QtWidgets import QScrollArea, QSplitter

from core.settings import Settings
from ui import pbo_builder
from ui.pbo_builder import PboBuilderPage, SettingsDialog


def test_builder_tab_matches_original_two_panel_layout(qtbot, monkeypatch, tmp_path):
    source = tmp_path / "sources" / "MyAddon"
    source.mkdir(parents=True)
    (source / "config.cpp").write_text("class CfgPatches {};", encoding="utf-8")
    (source / "$PBOPREFIX$").write_text("MyProject\\MyAddon\n", encoding="utf-8")
    output = tmp_path / "@MyMod"

    settings = Settings(
        pack_use_binarize=False,
        pack_convert_config=False,
        pbo_last_source_root=str(source),
        pbo_last_output_root=str(output),
    )
    monkeypatch.setattr(Settings, "save", lambda self: None)
    monkeypatch.setattr(pbo_builder, "get_logs_dir", lambda: tmp_path / "logs")

    page = PboBuilderPage(settings)
    qtbot.addWidget(page)
    page.resize(1000, 650)
    page.show()
    qtbot.wait(10)

    assert page.addon_list.count() == 1
    assert page.addon_list.item(0).text() == "MyAddon"
    assert page.findChild(QSplitter, "BuilderSplitter") is not None
    assert page.findChild(QScrollArea) is None
    assert page.build_button.text() == "Собрать PBO"
    assert page.settings_button.icon().isNull() is False

    page.select_all_addons()
    config = page._config()
    assert config.source_root == str(source)
    assert config.output_root_dir == str(output)
    assert config.selected_addons == ("MyAddon",)


def test_builder_settings_expose_context_menu_controls(qtbot, monkeypatch):
    settings = Settings(first_run_done=True)
    monkeypatch.setattr(Settings, "save", lambda self: None)
    monkeypatch.setattr("core.pbo_context_menu.is_installed", lambda: False)
    page = PboBuilderPage(settings)
    qtbot.addWidget(page)

    dialog = SettingsDialog(page.advanced_settings, page)
    qtbot.addWidget(dialog)

    assert "не установлен" in dialog.context_menu_status.text().lower()


def test_source_rows_keep_path_history(qtbot, monkeypatch, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    settings = Settings(
        pbo_last_source_root=str(first),
        pbo_source_roots=[str(first), str(second), str(first)],
    )
    monkeypatch.setattr(Settings, "save", lambda self: None)

    page = PboBuilderPage(settings)
    qtbot.addWidget(page)

    assert page.source_root_row.source_roots() == [str(first), str(second)]
    page.source_root_row.combo.setCurrentIndex(1)
    assert page.source_root_row.text() == str(second)
    page.source_root_row.remove_source_root()
    assert page.source_root_row.source_roots() == [str(first)]


def test_builder_tab_routes_server_addon_to_server_output(qtbot, monkeypatch, tmp_path):
    source_root = tmp_path / "sources"
    source = source_root / "Admin_SERVER"
    source.mkdir(parents=True)
    (source / "config.cpp").write_text("class CfgPatches {};", encoding="utf-8")
    client_output = tmp_path / "@Client"
    server_output = tmp_path / "@Server"

    settings = Settings(
        pack_use_binarize=False,
        pack_convert_config=False,
        pbo_last_source_root=str(source_root),
        pbo_last_output_root=str(client_output),
        pbo_last_output_server_root=str(server_output),
    )
    monkeypatch.setattr(Settings, "save", lambda self: None)
    monkeypatch.setattr(pbo_builder, "get_logs_dir", lambda: Path(tmp_path / "logs"))

    page = PboBuilderPage(settings)
    qtbot.addWidget(page)
    page.select_all_addons()
    config = page._config()

    assert config.selected_addons == ("Admin_SERVER",)
    assert config.output_root_dir == str(client_output)
    assert config.output_server_root_dir == str(server_output)
