"""Скрытая консоль для консольных DayZ Tools в собранной GUI-версии."""

from __future__ import annotations

import ctypes
import sys

_SW_HIDE = 0


def hide() -> bool:
    """Заводит скрытую консоль, если её нет. True — завели.

    Ничего не делает там, где консоль уже есть: из терминала мы работаем в ней,
    и прятать чужое окно нельзя.
    """
    if sys.platform != "win32":
        return False
    try:
        k = ctypes.windll.kernel32
        u = ctypes.windll.user32
        k.GetConsoleWindow.restype = ctypes.c_void_p
        if k.GetConsoleWindow():
            return False  # консоль уже есть — не трогаем
        if not k.AllocConsole():
            return False
        hwnd = k.GetConsoleWindow()
        if hwnd:
            u.ShowWindow(ctypes.c_void_p(hwnd), _SW_HIDE)
        return True
    except (AttributeError, OSError):
        # без консоли приложение работает, просто при запаковке будут окна
        return False
