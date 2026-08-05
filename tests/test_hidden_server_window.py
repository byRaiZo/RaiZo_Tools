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


def test_prepare_quit_restores_window():
    order = []
    win = cast(
        MainWindow,
        SimpleNamespace(
            _quitting=False,
            _restore_hidden_server_window=lambda: order.append("restore"),
        ),
    )

    assert MainWindow._prepare_quit(win) is True

    assert order == ["restore"]
    assert win._quitting is True


def test_quit_closes_after_successful_preparation():
    prepare = Mock(return_value=True)
    close = Mock()
    win = cast(MainWindow, SimpleNamespace(_prepare_quit=prepare, close=close))

    MainWindow.quit_app(win)

    prepare.assert_called_once_with()
    close.assert_called_once_with()


def test_close_button_quits_on_first_click_when_setting_is_enabled(monkeypatch):
    event = Mock()
    prepare = Mock(return_value=True)
    app_quit = Mock()
    monkeypatch.setattr("ui.main_window.QApplication.quit", app_quit)
    win = cast(
        MainWindow,
        SimpleNamespace(
            _quitting=False,
            settings=SimpleNamespace(quit_on_close=True),
            _prepare_quit=prepare,
            mini=SimpleNamespace(close=Mock()),
            packlog_window=SimpleNamespace(close=Mock()),
            tray=SimpleNamespace(hide=Mock()),
            log_server=SimpleNamespace(close=Mock()),
            log_client=SimpleNamespace(close=Mock()),
        ),
    )

    MainWindow.closeEvent(win, event)

    prepare.assert_called_once_with()
    event.ignore.assert_not_called()
    event.accept.assert_called_once_with()
    app_quit.assert_called_once_with()


def test_close_button_minimizes_to_tray_by_default():
    event = Mock()
    hide = Mock()
    show_mini = Mock()
    win = cast(
        MainWindow,
        SimpleNamespace(
            _quitting=False,
            settings=SimpleNamespace(quit_on_close=False),
            hide=hide,
            mini=SimpleNamespace(show_at_saved_pos=show_mini),
        ),
    )

    MainWindow.closeEvent(win, event)

    event.ignore.assert_called_once_with()
    hide.assert_called_once_with()
    show_mini.assert_called_once_with()


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
