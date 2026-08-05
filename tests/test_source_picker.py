from pathlib import Path
from typing import cast

from PySide6.QtWidgets import QFileDialog

from core.settings import Settings
from ui.mods_panel import pick_source_directory


def test_source_picker_uses_native_dialog_with_recent_start(monkeypatch, tmp_path: Path):
    recent = tmp_path / "recent"
    picked = tmp_path / "selected"
    recent.mkdir()
    picked.mkdir()
    settings = Settings(recent_source_dirs=[str(recent)])
    monkeypatch.setattr(Settings, "save", lambda self: None)
    call: dict[str, object] = {}

    def fake_picker(parent, caption, start, options):
        call.update(parent=parent, caption=caption, start=start, options=options)
        return str(picked)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake_picker)

    assert pick_source_directory(None, "Папка сорсов", settings) == str(picked)
    assert call["start"] == str(recent)
    options = cast(QFileDialog.Option, call["options"])
    assert not options & QFileDialog.Option.DontUseNativeDialog
