from __future__ import annotations

import threading
import uuid

from core.command_lock import process_command_lock


def test_named_mutex_serializes_concurrent_shortcut_commands():
    mutex_name = rf"Local\RaiZo_Tools_Test_{uuid.uuid4().hex}"
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first() -> None:
        with process_command_lock(name=mutex_name):
            first_entered.set()
            assert release_first.wait(2)

    def second() -> None:
        assert first_entered.wait(2)
        with process_command_lock(name=mutex_name):
            second_entered.set()

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    second_thread.start()

    assert first_entered.wait(2)
    assert not second_entered.wait(0.1)
    release_first.set()
    assert second_entered.wait(2)

    first_thread.join(2)
    second_thread.join(2)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()


def test_lock_can_be_released_while_first_command_keeps_monitoring():
    mutex_name = rf"Local\RaiZo_Tools_Test_{uuid.uuid4().hex}"
    second_entered = threading.Event()

    with process_command_lock(name=mutex_name) as first_lock:

        def second() -> None:
            with process_command_lock(name=mutex_name):
                second_entered.set()

        second_thread = threading.Thread(target=second)
        second_thread.start()
        assert not second_entered.wait(0.1)

        first_lock.release()
        assert second_entered.wait(2)
        second_thread.join(2)
        assert not second_thread.is_alive()
