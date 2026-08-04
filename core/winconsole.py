"""Чтение консоли сервера прямо из его окна.

Сервер пишет консольный текст в двух местах: в окно и в server_console.log.
Файл отстаёт чудовищно — движок сбрасывает его рывками: замер показал, что за
первые 26 секунд в файле не появилось ни байта, при том что в окне уже была
тысяча символов, а под конец окно набрало 21 тысячу, пока файл не трогали сорок
секунд. Для наблюдения за запуском это негодный источник.

Окно обновляется сразу. Внутри него один элемент RichEdit20A со всем текстом,
и его можно прочитать из чужого процесса запросом WM_GETTEXT. GetWindowText для
этого не годится: он намеренно не обращается к окнам других процессов.

Работает и когда окно спрятано — проверено: видимых окон ноль, текст набегает.

Цена вопроса измерена: ни сервер, ни мы не тратим на это процессор совсем —
ноль процентов у обоих. Сотня миллисекунд, которую занимает запрос, уходит на
ожидание в очереди сообщений сервера; поток в это время спит. Но именно поэтому
опрос обязан жить не на главном потоке: дважды в секунду замирать на сотню
миллисекунд — это заметное подёргивание интерфейса.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes

from PySide6.QtCore import QThread, Signal

_WM_GETTEXT = 0x000D
_WM_GETTEXTLENGTH = 0x000E
_SMTO_ABORTIFHUNG = 0x0002

# Сколько ждём ответа сервера. Обычный SendMessage ждёт вечно, и зависший
# сервер утянул бы наш поток за собой; со сроком мы просто пропустим такт.
_TIMEOUT_MS = 1500

_POLL_MS = 500  # частота опроса
_FIND_TRIES = 40  # сколько тактов ищем окно, прежде чем сдаться


def _u32():
    u = ctypes.windll.user32
    u.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        ctypes.c_uint,
        wintypes.WPARAM,
        wintypes.LPARAM,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    u.SendMessageTimeoutW.restype = wintypes.LPARAM
    return u


def find_control(pid: int) -> int | None:
    """Элемент с текстом консоли внутри окна процесса."""
    u = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def top(hwnd, _param):
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def kid(child, _p):
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(child, cls, 64)
            if "Edit" in cls.value:  # RichEdit20A у сервера DayZ
                found.append(child)
            return True

        u.EnumChildWindows(hwnd, kid, 0)
        return True

    u.EnumWindows(top, 0)
    return found[0] if found else None


def _ask(u, hwnd: int, msg: int, wparam: int = 0, lparam: int = 0) -> int | None:
    """Запрос к чужому окну с ограничением по времени. None — не ответило."""
    res = ctypes.c_size_t(0)
    ok = u.SendMessageTimeoutW(
        wintypes.HWND(hwnd), msg, wparam, lparam, _SMTO_ABORTIFHUNG, _TIMEOUT_MS, ctypes.byref(res)
    )
    return None if not ok else int(res.value)


class WindowConsole(QThread):
    """Поток, отдающий новый текст консоли сервера по мере появления."""

    lines = Signal(list)  # новые строки
    unavailable = Signal()  # окна нет — вызывающему пора на запасной путь

    def __init__(self, pid: int, parent=None):
        super().__init__(parent)
        self.pid = pid
        self._stop = False
        self._seen = 0  # сколько символов уже отдали

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        u = _u32()
        hwnd = None
        for _ in range(_FIND_TRIES):
            if self._stop:
                return
            hwnd = find_control(self.pid)
            if hwnd:
                break
            self.msleep(_POLL_MS)
        if not hwnd:
            self.unavailable.emit()
            return

        while not self._stop:
            n = _ask(u, hwnd, _WM_GETTEXTLENGTH)
            if n is None:
                # окно исчезло или не отвечает: сервер закрылся либо завис
                self.unavailable.emit()
                return
            if n != self._seen:
                if n < self._seen:
                    # движок подрезал свой буфер — начинаем считать заново
                    self._seen = 0
                buf = ctypes.create_unicode_buffer(n + 2)
                got = _ask(u, hwnd, _WM_GETTEXT, n + 1, ctypes.addressof(buf))
                if got is None:
                    self.unavailable.emit()
                    return
                text = buf.value
                fresh = text[self._seen :]
                self._seen = len(text)
                out = [ln.rstrip() for ln in fresh.replace("\r", "\n").split("\n")]
                out = [ln for ln in out if ln]
                if out:
                    self.lines.emit(out)
            self.msleep(_POLL_MS)
