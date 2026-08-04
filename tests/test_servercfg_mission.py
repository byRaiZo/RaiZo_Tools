import codecs

from core.servercfg import ServerCfg, sync_mission_for_launch


def test_sync_existing_mission_template_preserves_comments_and_utf8(tmp_path):
    path = tmp_path / "serverDZ.cfg"
    path.write_text(
        "// Комментарий\nclass Missions\n{\n    class DayZ\n    {\n"
        '        template = "old.chernarusplus"; // оставить\n    };\n};\n',
        encoding="utf-8",
    )

    changed, reencoded = sync_mission_for_launch(path, "dayzOffline.chernarusplus")

    raw = path.read_bytes()
    text = raw.decode("utf-8")
    assert changed is True
    assert reencoded is False
    assert not raw.startswith(codecs.BOM_UTF8)
    assert 'template = "dayzOffline.chernarusplus"; // оставить' in text
    assert "// Комментарий" in text


def test_sync_adds_missions_block_when_cfg_has_no_template(tmp_path):
    path = tmp_path / "serverDZ.cfg"
    path.write_text('hostname = "Test";\n', encoding="utf-8")

    changed, _reencoded = sync_mission_for_launch(path, "dayzOffline.sakhal")

    text = path.read_text(encoding="utf-8")
    assert changed is True
    assert 'template = "dayzOffline.sakhal";' in text
    assert "class Missions" in text


def test_unchanged_template_does_not_rewrite_cfg(tmp_path, monkeypatch):
    path = tmp_path / "serverDZ.cfg"
    path.write_text(
        'class Missions {\n    class DayZ {\n        template = "dayzOffline.enoch";\n    };\n};\n',
        encoding="utf-8",
    )
    save = ServerCfg.save
    saved = []

    def track_save(self):
        saved.append(True)
        save(self)

    monkeypatch.setattr(ServerCfg, "save", track_save)

    changed, reencoded = sync_mission_for_launch(path, "dayzOffline.enoch")

    assert changed is False
    assert reencoded is False
    assert saved == []
