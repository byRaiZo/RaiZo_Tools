from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

from ui.launch_status import CLIENT, PROC_OFF, SERVER
from ui.main_window import MainWindow


def _window(side: str):
    monitor = Mock()
    status = Mock()
    identity = object()
    win = cast(
        MainWindow,
        SimpleNamespace(
            server_pid=42 if side == SERVER else 84,
            client_pid=84 if side == CLIENT else 24,
            server_identity=identity if side == SERVER else object(),
            client_identity=identity if side == CLIENT else object(),
            _stopping={"server_pid": 1.0, "client_pid": 1.0},
            _alive={"server_pid": True, "client_pid": True},
            _hidden_server=(42, 1.0),
            monitors={SERVER: monitor, CLIENT: Mock()},
            launch_status=status,
            _console_stop=Mock(),
            _append_log=Mock(),
            _side_name=Mock(return_value="Сервер" if side == SERVER else "Клиент"),
            _update_launch_button=Mock(),
        ),
    )
    return win, identity, monitor, status


def test_fatal_server_launch_error_stops_only_owned_server(monkeypatch):
    win, identity, monitor, status = _window(SERVER)
    killed = Mock(return_value=True)
    monkeypatch.setattr("ui.main_window.kill_pid", killed)

    assert MainWindow._stop_crashed_process(win, SERVER) is True

    killed.assert_called_once_with(identity)
    assert win.server_pid is None
    assert win.server_identity is None
    assert win.client_pid == 24
    assert win._hidden_server is None
    assert "server_pid" not in win._stopping
    monitor.stop.assert_called_once_with()
    cast(Mock, win._console_stop).assert_called_once_with()
    status.set_process_state.assert_called_once_with(SERVER, PROC_OFF)


def test_failed_automatic_stop_keeps_process_controllable(monkeypatch):
    win, identity, monitor, status = _window(SERVER)
    monkeypatch.setattr("ui.main_window.kill_pid", Mock(return_value=False))
    monkeypatch.setattr("ui.main_window.psutil.pid_exists", lambda _pid: True)

    assert MainWindow._stop_crashed_process(win, SERVER) is False

    assert win.server_pid == 42
    assert win.server_identity is identity
    monitor.stop.assert_not_called()
    cast(Mock, win._console_stop).assert_not_called()
    status.set_process_state.assert_not_called()
