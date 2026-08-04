from types import MethodType, SimpleNamespace
from typing import cast
from unittest.mock import Mock

import psutil

from ui.main_window import MainWindow


def test_restore_shows_only_same_hidden_server(monkeypatch):
    proc = SimpleNamespace(is_running=lambda: True, create_time=lambda: 123.0)
    monkeypatch.setattr(psutil, "Process", lambda _pid: proc)
    shown = Mock(return_value=1)
    monkeypatch.setattr("ui.main_window.winhide.show", shown)
    win = cast(MainWindow, SimpleNamespace(_hidden_server=(42, 123.0)))

    assert MainWindow._restore_hidden_server_window(win) == 1
    assert win._hidden_server is None
    shown.assert_called_once_with(42)


def test_restore_ignores_reused_pid(monkeypatch):
    proc = SimpleNamespace(is_running=lambda: True, create_time=lambda: 999.0)
    monkeypatch.setattr(psutil, "Process", lambda _pid: proc)
    shown = Mock(return_value=1)
    monkeypatch.setattr("ui.main_window.winhide.show", shown)
    win = cast(MainWindow, SimpleNamespace(_hidden_server=(42, 123.0)))

    assert MainWindow._restore_hidden_server_window(win) == 0
    shown.assert_not_called()


def test_quit_restores_window_before_closing():
    order = []
    win = cast(
        MainWindow,
        SimpleNamespace(
            _quitting=False,
            _restore_hidden_server_window=lambda: order.append("restore"),
            close=lambda: order.append("close"),
        ),
    )

    MainWindow.quit_app(win)

    assert order == ["restore", "close"]
    assert win._quitting is True


def test_adopted_server_is_hidden_when_setting_is_enabled(monkeypatch):
    proc = SimpleNamespace(create_time=lambda: 123.0)
    monkeypatch.setattr(psutil, "Process", lambda _pid: proc)
    hidden = Mock(return_value=1)
    monkeypatch.setattr("ui.main_window.winhide.hide_existing", hidden)
    win = cast(
        MainWindow,
        SimpleNamespace(
            settings=SimpleNamespace(hide_server_window=True),
            _hidden_server=None,
        ),
    )
    win._remember_hidden_server = MethodType(MainWindow._remember_hidden_server, win)

    assert MainWindow._hide_adopted_server(win, 42) == 1
    assert win._hidden_server == (42, 123.0)
    hidden.assert_called_once_with(42)


def test_adopted_server_stays_visible_when_setting_is_disabled(monkeypatch):
    hidden = Mock(return_value=1)
    monkeypatch.setattr("ui.main_window.winhide.hide_existing", hidden)
    win = cast(
        MainWindow,
        SimpleNamespace(
            settings=SimpleNamespace(hide_server_window=False),
            _hidden_server=(1, 1.0),
        ),
    )
    win._remember_hidden_server = MethodType(MainWindow._remember_hidden_server, win)

    assert MainWindow._hide_adopted_server(win, 42) == 0
    assert win._hidden_server is None
    hidden.assert_not_called()
