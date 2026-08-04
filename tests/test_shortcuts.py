from __future__ import annotations

from pathlib import Path

import pytest

from core.shortcuts import command_for_preset, create_shortcut, icon_for_shortcut


class FakeShortcut:
    def __init__(self) -> None:
        self.saved = False
        self.TargetPath = ""
        self.Arguments = ""
        self.WorkingDirectory = ""
        self.IconLocation = ""
        self.Description = ""

    def Save(self) -> None:
        self.saved = True


class FakeShell:
    def __init__(self) -> None:
        self.path = ""
        self.shortcut = FakeShortcut()

    def CreateShortcut(self, path: str) -> FakeShortcut:
        self.path = path
        return self.shortcut


def test_shortcut_command_contains_exact_preset_action_and_target():
    command = command_for_preset("Diag Chernarus", "start", "all")
    assert "server start" in command.arguments
    assert '--preset "Diag Chernarus"' in command.arguments
    assert "--target all" in command.arguments
    assert "--quiet --no-wait" in command.arguments
    assert "--show-server-window" in command.arguments


def test_stop_shortcut_does_not_need_window_override():
    command = command_for_preset("Diag", "stop", "server")
    assert "--show-server-window" not in command.arguments


def test_create_shortcut_sets_windows_link_fields(tmp_path: Path):
    shell = FakeShell()
    result = create_shortcut(tmp_path / "run-server", "Diag", "stop", "server", shell=shell)
    assert result == tmp_path / "run-server.lnk"
    assert shell.path == str(result)
    assert shell.shortcut.saved
    assert shell.shortcut.TargetPath
    assert "server stop" in shell.shortcut.Arguments
    assert "--target server" in shell.shortcut.Arguments
    assert shell.shortcut.IconLocation.endswith("server-stop.ico,0")


@pytest.mark.parametrize("action", ["start", "stop"])
@pytest.mark.parametrize("target", ["server", "client", "all"])
def test_every_shortcut_icon_is_bundled(action: str, target: str):
    icon = icon_for_shortcut(action, target)
    assert icon.is_file()
    assert icon.name == f"{target}-{action}.ico"
