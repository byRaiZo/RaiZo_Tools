"""Скрытие окна запущенной программы.

Окно сервера DayZ — обычное диалоговое окно Windows (класс #32770) с
заголовком вида «DayZ Console version (64bit) 1.29.163451 : port 2302». Всё,
что в нём видно, сервер одновременно пишет в server_console.log, который мы и
так читаем, — то есть окно не несёт ни одной строки, которой у нас нет.

Способов убрать его два, и они дополняют друг друга:

  * при запуске — попросить Windows не показывать первое окно процесса
    (STARTUPINFO). Дёшево, но выполняется на усмотрение самой программы:
    многие этот признак игнорируют;
  * после запуска — найти окно по номеру процесса и скрыть. Надёжно, но окно
    успевает мелькнуть: появляется оно через секунду-другую после старта.

Первый пробуем всегда, второй подчищает за ним. По тому, нашёл ли второй что
скрывать, видно, сработал ли первый.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import time

_SW_HIDE, _SW_SHOW = 0, 5
_WM_CLOSE = 0x0010
_STARTF_USESHOWWINDOW = 0x00000001

# Окна, которые прятать не надо: служебные окна ввода есть у любой программы,
# они и так невидимы, и трогать их незачем.
_SKIP_CLASSES = {"IME", "MSCTFIME UI"}


def _user32():
    return ctypes.windll.user32


def startupinfo():
    """STARTUPINFO с просьбой не показывать окно. Отдаётся в subprocess.Popen.

    Именно просьба: Windows передаёт этот признак программе, а показывать окно
    или нет, решает она сама. Поэтому одного этого способа мало.
    """
    import subprocess

    si = subprocess.STARTUPINFO()
    si.dwFlags |= _STARTF_USESHOWWINDOW
    si.wShowWindow = _SW_HIDE
    return si


def windows_of(pid: int, visible_only: bool = True) -> list[int]:
    """Окна верхнего уровня, принадлежащие процессу."""
    u = _user32()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _param):
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        if visible_only and not u.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        if cls.value in _SKIP_CLASSES:
            return True
        found.append(hwnd)
        return True

    u.EnumWindows(collect, 0)
    return found


def hide(pid: int, timeout: float = 20.0, poll: float = 0.3) -> tuple[int, float]:
    """Ждёт появления окон процесса и скрывает их.

    Возвращает (сколько скрыто, через сколько секунд). Ноль означает, что за
    отведённое время видимых окон не появилось: либо сработала просьба при
    запуске, либо программа окон и не заводит.
    """
    u = _user32()
    t0 = time.time()
    while time.time() - t0 < timeout:
        wins = windows_of(pid)
        if wins:
            for hwnd in wins:
                u.ShowWindow(wintypes.HWND(hwnd), _SW_HIDE)
            return len(wins), time.time() - t0
        time.sleep(poll)
    return 0, time.time() - t0


def hide_existing(pid: int) -> int:
    """Скрывает уже существующие видимые окна процесса без ожидания."""
    u = _user32()
    wins = windows_of(pid)
    for hwnd in wins:
        u.ShowWindow(wintypes.HWND(hwnd), _SW_HIDE)
    return len(wins)


def show(pid: int) -> int:
    """Возвращает скрытые окна процесса. Сколько показано — столько и вернём."""
    u = _user32()
    wins = windows_of(pid, visible_only=False)
    for hwnd in wins:
        u.ShowWindow(wintypes.HWND(hwnd), _SW_SHOW)
    return len(wins)


def ask_close(pid: int) -> int:
    """Просит окна процесса закрыться — то же, что нажать крестик мышью.

    Это самый мягкий способ, доступный без RCON: программа получает обычное
    сообщение о закрытии и завершается своим порядком, а не обрывается
    посреди работы, как при убийстве процесса.

    Сообщение отправляется без ожидания ответа: закрытие сервера занимает
    секунды, и держать всё это время интерфейс нельзя. Сколько окон попросили —
    столько и вернём; ноль означает, что просить оказалось некого.
    """
    u = _user32()
    wins = windows_of(pid, visible_only=False)
    for hwnd in wins:
        u.PostMessageW(wintypes.HWND(hwnd), _WM_CLOSE, 0, 0)
    return len(wins)
