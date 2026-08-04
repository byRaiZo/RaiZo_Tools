"""Управление пунктом упаковки PBO в контекстном меню Windows."""

from __future__ import annotations

import os
import subprocess
import sys
import winreg
from pathlib import Path
from typing import Any

MENU_KEY = r"Software\Classes\Directory\shell\RaiZoTools.PackPBO"
COMMAND_KEY = MENU_KEY + r"\command"
MENU_TITLE = "Собрать PBO — RaiZo Tools"


def _application_parts(
    executable: Path | None = None,
    main_script: Path | None = None,
) -> tuple[Path, Path | None]:
    if executable is not None:
        return executable, main_script
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return executable, None
    return executable, Path(__file__).resolve().parents[1] / "main.py"


def command_line(
    *,
    executable: Path | None = None,
    main_script: Path | None = None,
) -> str:
    """Команда реестра; настройки и приватный ключ остаются только в JSON."""
    executable, main_script = _application_parts(executable, main_script)
    parts = [str(executable)]
    if main_script is not None:
        parts.append(str(main_script))
    prefix = subprocess.list2cmdline(parts)
    return f'{prefix} --pack-folder "%V" --saved-options'


def install(
    *,
    executable: Path | None = None,
    main_script: Path | None = None,
    registry: Any = winreg,
) -> None:
    """Регистрирует меню только для текущего пользователя, без прав администратора."""
    executable, main_script = _application_parts(executable, main_script)
    with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, MENU_KEY, 0, registry.KEY_WRITE) as key:
        registry.SetValueEx(key, "", 0, registry.REG_SZ, MENU_TITLE)
        registry.SetValueEx(key, "Icon", 0, registry.REG_SZ, str(executable))
    with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, COMMAND_KEY, 0, registry.KEY_WRITE) as key:
        registry.SetValueEx(
            key,
            "",
            0,
            registry.REG_SZ,
            command_line(executable=executable, main_script=main_script),
        )


def remove(*, registry: Any = winreg) -> None:
    """Удаляет только ключи, принадлежащие RaiZo Tools."""
    for path in (COMMAND_KEY, MENU_KEY):
        try:
            registry.DeleteKey(registry.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (2, None):
                raise


def is_installed(*, registry: Any = winreg) -> bool:
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, COMMAND_KEY, 0, registry.KEY_READ) as key:
            value, _kind = registry.QueryValueEx(key, "")
    except (FileNotFoundError, OSError):
        return False
    return bool(str(value).strip())


def refresh_if_installed() -> None:
    """После обновления переносит зарегистрированную команду на текущий EXE."""
    try:
        if os.name == "nt" and is_installed():
            install()
    except OSError:
        pass
