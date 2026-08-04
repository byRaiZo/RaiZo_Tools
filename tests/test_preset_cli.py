from __future__ import annotations

import pytest

import core.preset_cli as preset_cli
from core.launch_control import find_preset, select_target
from core.preset_cli import build_parser, is_preset_cli_invocation
from core.presets import ServerPreset
from core.settings import Settings


def test_preset_cli_marker_does_not_capture_pbo_cli():
    assert is_preset_cli_invocation(["server", "start", "--preset", "Diag"])
    assert is_preset_cli_invocation(["preset", "stop", "--preset", "Diag"])
    assert not is_preset_cli_invocation(["-pack", "source", "output"])


def test_parser_accepts_action_target_and_preset():
    args = build_parser().parse_args(["start", "--preset", "Diag", "--target", "server", "--show-server-window"])
    assert args.action == "start"
    assert args.preset == "Diag"
    assert args.target == "server"
    assert args.show_server_window


def test_find_preset_by_name_and_file_stem():
    diag = ServerPreset(name="Diag", mission="dayzOffline.chernarusplus")
    assert find_preset("diag", [diag]) is diag
    assert find_preset(diag.file_stem(), [diag]) is diag


def test_duplicate_display_name_requires_file_stem():
    presets = [
        ServerPreset(name="Dev", mission="dayzOffline.chernarusplus"),
        ServerPreset(name="Dev", mission="dayzOffline.enoch"),
    ]
    with pytest.raises(ValueError, match="неоднозначно"):
        find_preset("Dev", presets)
    assert find_preset(presets[1].file_stem(), presets) is presets[1]


@pytest.mark.parametrize(
    ("target", "server", "client"),
    [("server", True, False), ("client", False, True), ("all", True, True)],
)
def test_select_target_does_not_modify_saved_preset(target: str, server: bool, client: bool):
    original = ServerPreset(name="Dev", launch_server=False, launch_client=False)
    selected = select_target(original, target)
    assert (selected.launch_server, selected.launch_client) == (server, client)
    assert (original.launch_server, original.launch_client) == (False, False)


def test_shortcut_override_shows_server_without_changing_saved_setting(monkeypatch):
    saved = Settings(hide_server_window=True)
    seen: dict[str, bool] = {}

    class Registry:
        def scan(self) -> None:
            pass

    monkeypatch.setattr(preset_cli.Settings, "load", lambda: saved)
    monkeypatch.setattr(preset_cli, "migrate_legacy_v2", lambda: None)
    monkeypatch.setattr(preset_cli.i18n, "load", lambda _language: None)
    monkeypatch.setattr(preset_cli, "find_preset", lambda _name: ServerPreset(name="Diag"))
    monkeypatch.setattr(preset_cli, "ModRegistry", lambda _settings: Registry())
    monkeypatch.setattr(preset_cli, "prepare_launch", lambda *_args: [])

    def fake_start(_preset, settings, _branch, _registry, _log, *, force_restart=False):
        seen["hide"] = settings.hide_server_window
        seen["force"] = force_restart
        return ""

    monkeypatch.setattr(preset_cli, "start_preset", fake_start)
    result = preset_cli.run_preset_cli(
        [
            "server",
            "start",
            "--preset",
            "Diag",
            "--target",
            "server",
            "--quiet",
            "--no-wait",
        ]
    )
    assert result == 0
    assert seen["hide"] is False
    assert seen["force"] is True
    assert saved.hide_server_window is True
