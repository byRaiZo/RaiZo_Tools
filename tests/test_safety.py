from core.downloader import safe_member


def test_zip_slip_is_rejected(tmp_path):
    assert safe_member("../../evil.exe", tmp_path) is None
    assert safe_member("C:/evil.exe", tmp_path) is None
    assert safe_member("mission/db/globals.xml", tmp_path) == (tmp_path / "mission" / "db" / "globals.xml")


def test_no_persistence_delete_api():
    import core.layout as layout

    assert not hasattr(layout, "clear_mission_storage")
    assert not hasattr(layout, "clear_profile")
    assert not hasattr(layout, "delete_preset_files")
