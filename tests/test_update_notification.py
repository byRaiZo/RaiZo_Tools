from types import MethodType, SimpleNamespace
from typing import cast
from unittest.mock import Mock

from core import updater
from ui.main_window import MainWindow


def _window(*, seen: str = "") -> MainWindow:
    win = cast(
        MainWindow,
        SimpleNamespace(
            settings=SimpleNamespace(update_seen=seen),
            _upd_release=None,
            _upd_state="",
            _update_nav_item=Mock(),
            _open_update=Mock(),
        ),
    )
    win._on_update_checked = MethodType(MainWindow._on_update_checked, win)
    win._open_unseen_update = MethodType(MainWindow._open_unseen_update, win)
    return win


def test_startup_check_offers_unseen_update_once(monkeypatch):
    rel = updater.Release("1.0.2", "v1.0.2", "Changes", "https://example.invalid")
    win = _window()
    scheduled = []
    monkeypatch.setattr(updater, "is_update", lambda value: value is rel)
    monkeypatch.setattr("ui.main_window.QTimer.singleShot", lambda _delay, callback: scheduled.append(callback))

    MainWindow._on_update_checked(win, rel)

    assert win._upd_release is rel
    assert win._upd_state == "available"
    assert len(scheduled) == 1
    scheduled[0]()
    cast(Mock, win._open_update).assert_called_once_with()


def test_startup_check_does_not_reopen_seen_update(monkeypatch):
    rel = updater.Release("1.0.2", "v1.0.2", "Changes", "https://example.invalid")
    win = _window(seen="1.0.2")
    scheduled = Mock()
    monkeypatch.setattr(updater, "is_update", lambda value: value is rel)
    monkeypatch.setattr("ui.main_window.QTimer.singleShot", scheduled)

    MainWindow._on_update_checked(win, rel)

    scheduled.assert_not_called()


def test_manual_check_opens_only_one_dialog(monkeypatch):
    rel = updater.Release("1.0.2", "v1.0.2", "Changes", "https://example.invalid")
    win = _window()
    scheduled = Mock()
    monkeypatch.setattr(updater, "is_update", lambda value: value is rel)
    monkeypatch.setattr("ui.main_window.QTimer.singleShot", scheduled)

    MainWindow._on_manual_checked(win, rel)

    scheduled.assert_not_called()
    cast(Mock, win._open_update).assert_called_once_with()
