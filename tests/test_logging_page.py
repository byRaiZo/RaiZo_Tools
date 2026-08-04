import os

from ui.log_window import LogWindow, LogsInterface


def _script(path, text: str, mtime: int) -> None:
    path.write_text(text + "\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_log_panel_opens_latest_file_immediately_and_follows_rotation(qtbot, tmp_path):
    _script(tmp_path / "script_2026-01-01_00-00-00.log", "old line", 100)
    latest = tmp_path / "script_2026-01-02_00-00-00.log"
    _script(latest, "latest line", 200)

    panel = LogWindow("Server", key="server")
    qtbot.addWidget(panel)
    panel.set_directory(tmp_path)
    assert not panel.timer.isActive()

    panel.set_active(True)
    qtbot.waitUntil(lambda: "latest line" in panel.view.toPlainText())
    assert "old line" not in panel.view.toPlainText()

    rotated = tmp_path / "script_2026-01-03_00-00-00.log"
    _script(rotated, "rotated line", 300)
    qtbot.waitUntil(lambda: "rotated line" in panel.view.toPlainText(), timeout=1500)
    assert "latest line" not in panel.view.toPlainText()

    newest = tmp_path / "script_2026-01-04_00-00-00.log"
    _script(newest, "newest line", 400)
    qtbot.waitUntil(lambda: "newest line" in panel.view.toPlainText(), timeout=1500)
    text = panel.view.toPlainText()
    assert "rotated line" not in text
    assert "latest line" not in text


def test_logs_page_tracks_only_selected_side(qtbot, tmp_path):
    server_dir = tmp_path / "server"
    client_dir = tmp_path / "client"
    server_dir.mkdir()
    client_dir.mkdir()
    _script(server_dir / "script_2026-01-01_00-00-00.log", "server", 100)
    _script(client_dir / "script_2026-01-01_00-00-00.log", "client", 100)

    server = LogWindow("Server", key="server")
    client = LogWindow("Client", key="client")
    server.set_directory(server_dir)
    client.set_directory(client_dir)
    page = LogsInterface(server, client)
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(server.timer.isActive)

    assert not client.timer.isActive()
    page.tabs.setCurrentWidget(client)
    qtbot.waitUntil(client.timer.isActive)
    assert not server.timer.isActive()
