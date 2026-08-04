"""Создание Windows-ярлыков для команд управления пресетом."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ShortcutCommand:
    executable: Path
    arguments: str
    working_directory: Path


def icon_for_shortcut(action: str, target: str) -> Path:
    """ICO из dev-server-scripts для пары start/stop × server/client/all."""
    operation = "start" if action == "start" else "stop"
    return Path(__file__).resolve().parent / "shortcut_icons" / f"{target}-{operation}.ico"


def command_for_preset(preset: str, action: str, target: str) -> ShortcutCommand:
    args = ["server", action, "--preset", preset, "--target", target, "--quiet", "--no-wait"]
    if action == "start":
        args.append("--show-server-window")
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
    else:
        executable = Path(sys.executable).resolve()
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.is_file():
            executable = pythonw
        args.insert(0, str(Path(__file__).resolve().parent.parent / "main.py"))
    return ShortcutCommand(executable, subprocess.list2cmdline(args), executable.parent)


def default_desktop() -> Path:
    """Возвращает системную папку «Рабочий стол», включая OneDrive-перенос."""
    if sys.platform == "win32":
        try:
            shell32 = ctypes.windll.shell32
            buffer = ctypes.create_unicode_buffer(32768)
            # CSIDL_DESKTOPDIRECTORY учитывает перенос рабочего стола в OneDrive.
            if shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:
                return Path(buffer.value)
        except (AttributeError, OSError, ValueError):
            pass
    return Path.home() / "Desktop"


def create_shortcut(path: Path, preset: str, action: str, target: str, shell=None) -> Path:
    """Создаёт настоящий ``.lnk`` через Windows Script Host COM."""
    destination = path.with_suffix(".lnk")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = command_for_preset(preset, action, target)
    if shell is None:
        if sys.platform != "win32":
            raise OSError("Создание .lnk поддерживается только в Windows")
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(destination))
    shortcut.TargetPath = str(command.executable)
    shortcut.Arguments = command.arguments
    shortcut.WorkingDirectory = str(command.working_directory)
    icon = icon_for_shortcut(action, target)
    shortcut.IconLocation = f"{icon if icon.is_file() else command.executable},0"
    shortcut.Description = f"RaiZo Tools: {action} {target}, {preset}"
    shortcut.Save()
    return destination
