from core import packlog


def _write_log(tmp_path, text: str) -> None:
    (tmp_path / "Addon.packing.log").write_text(text, encoding="utf-8")


def test_zero_summary_lines_are_not_counted_as_issues(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(packlog, "temp_dir", lambda: tmp_path)
    _write_log(tmp_path, "Errors: 0\nWarnings: 0\n")

    report = packlog.read("Addon", packlog.PACKING)

    assert report.clean is True
    assert report.errors == 0
    assert report.warnings == 0
    assert report.marked_lines() == []


def test_nonzero_summary_uses_declared_count_when_details_are_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(packlog, "temp_dir", lambda: tmp_path)
    _write_log(tmp_path, "Warnings: 3\nErrors: 2\n")

    report = packlog.read("Addon", packlog.PACKING)

    assert report.warnings == 3
    assert report.errors == 2
    assert report.marked_lines() == ["Warnings: 3", "Errors: 2"]


def test_summary_line_is_hidden_when_detailed_error_exists(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(packlog, "temp_dir", lambda: tmp_path)
    _write_log(tmp_path, "ERROR: broken config\nErrors: 1\nWarnings: 0\n")

    report = packlog.read("Addon", packlog.PACKING)

    assert report.errors == 1
    assert report.warnings == 0
    assert report.marked_lines() == ["ERROR: broken config"]
