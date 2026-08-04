from __future__ import annotations

import pytest

from core import persistence


def test_wipe_removes_only_direct_storage_directories(tmp_path):
    mission = tmp_path / "dayzOffline.chernarusplus"
    storage_1 = mission / "storage_1"
    storage_backup = mission / "Storage_backup"
    ordinary = mission / "db"
    nested_storage = ordinary / "storage_2"
    storage_file = mission / "storage_note"

    for directory in (storage_1, storage_backup, nested_storage):
        directory.mkdir(parents=True)
        (directory / "data.bin").write_bytes(b"data")
    storage_file.write_text("keep", encoding="utf-8")

    assert persistence.wipe_storage(mission) == 2
    assert not storage_1.exists()
    assert not storage_backup.exists()
    assert nested_storage.exists()
    assert storage_file.exists()


def test_wipe_rejects_storage_junction_or_symlink(monkeypatch, tmp_path):
    mission = tmp_path / "mission"
    storage = mission / "storage_1"
    storage.mkdir(parents=True)
    monkeypatch.setattr(persistence, "_is_reparse_directory", lambda path: path == storage)

    with pytest.raises(persistence.StorageWipeError, match="ссылки запрещён"):
        persistence.wipe_storage(mission)

    assert storage.exists()


def test_wipe_requires_existing_mission_directory(tmp_path):
    with pytest.raises(persistence.StorageWipeError, match="не найдена"):
        persistence.wipe_storage(tmp_path / "missing")
