from core import packlog
from ui.packlog_window import PackLogWindow


def test_pack_logs_use_one_window_with_two_tabs(qtbot, monkeypatch) -> None:
    calls: list[tuple[tuple[str, ...], str]] = []

    def fake_read_all(names: list[str], kind: str):
        calls.append((tuple(names), kind))
        return []

    monkeypatch.setattr(packlog, "read_all", fake_read_all)

    window = PackLogWindow()
    qtbot.addWidget(window)
    window.set_names(["ClientAddon", "ServerAddon"])

    assert window.tabs.count() == 2
    assert set(window.pages) == {packlog.PACKING, packlog.BINARIZE}
    assert calls == [
        (("ClientAddon", "ServerAddon"), packlog.PACKING),
        (("ClientAddon", "ServerAddon"), packlog.BINARIZE),
    ]
