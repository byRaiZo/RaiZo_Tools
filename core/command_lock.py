"""Межпроцессная блокировка команд запуска и остановки DayZ."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import win32api
import win32event

MUTEX_NAME = r"Local\RaiZo_Tools_DayZ_Command_v1"


class ProcessCommandLock:
    """Windows mutex, который можно временно отпустить и получить снова."""

    def __init__(self, timeout_ms: int, name: str) -> None:
        # pywin32 принимает None и собственный PyHANDLE, но его type stubs
        # ошибочно требуют SECURITY_ATTRIBUTES и обычный int.
        self._handle: Any = win32event.CreateMutex(cast(Any, None), False, name)
        self._timeout_ms = timeout_ms
        self.acquired = False
        self._closed = False

    def acquire(self) -> None:
        if self.acquired:
            return
        result = win32event.WaitForSingleObject(self._handle, self._timeout_ms)
        if result not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
            if result == win32event.WAIT_TIMEOUT:
                raise TimeoutError("Другая команда запуска или остановки ещё выполняется")
            raise OSError(f"Не удалось получить блокировку команд DayZ: код {result}")
        self.acquired = True

    def release(self) -> None:
        if not self.acquired:
            return
        win32event.ReleaseMutex(self._handle)
        self.acquired = False

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.release()
        finally:
            win32api.CloseHandle(self._handle)
            self._closed = True


@contextmanager
def process_command_lock(
    timeout_ms: int = win32event.INFINITE,
    name: str = MUTEX_NAME,
) -> Iterator[ProcessCommandLock]:
    """Не даёт GUI и нескольким ярлыкам менять процессы одновременно."""
    lock = ProcessCommandLock(timeout_ms, name)
    try:
        lock.acquire()
        yield lock
    finally:
        lock.close()
