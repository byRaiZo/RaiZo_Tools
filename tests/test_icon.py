from ui.theme import ICON_FILE, outside_icon


def test_ready_ico_loads(qtbot):
    del qtbot
    assert ICON_FILE.is_file()
    assert not outside_icon().isNull()
