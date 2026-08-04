import json

import core.migration as migration
import core.presets as presets
import core.settings as settings_module


def test_legacy_v2_is_migrated_with_backup(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    settings_file = config_dir / "settings.json"
    presets_dir = config_dir / "presets"
    mod_presets_dir = config_dir / "mod_presets"
    for module in (settings_module, migration):
        monkeypatch.setattr(module, "APP_DIR", tmp_path)
        monkeypatch.setattr(module, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(module, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(presets, "PRESETS_DIR", presets_dir)
    monkeypatch.setattr(presets, "MOD_PRESETS_DIR", mod_presets_dir)

    legacy = {
        "schemaVersion": 2,
        "active": {
            "language": "ru",
            "serverPreset": "Default",
            "modPreset": "Modded",
        },
        "serverPresets": {
            "Default": {
                "gamePath": "F:/DayZ",
                "serverPath": "F:/DayZServer",
                "missionName": "dayzOffline.chernarusplus",
                "serverPort": 2402,
                "serverIp": "192.168.1.10",
                "serverConfig": "serverDZ.cfg",
                "runtimeMode": "standard",
                "filePatching": True,
                "cleanLogs": "all",
                "showServerWindow": False,
            }
        },
        "modPresets": {
            "Modded": {
                "client": ["$steam/@CF"],
                "server": ["$local/@ServerOnly"],
            }
        },
    }
    (tmp_path / "config.json").write_text(json.dumps(legacy), encoding="utf-8")

    assert migration.migrate_legacy_v2()
    migrated = json.loads(settings_file.read_text(encoding="utf-8"))
    assert migrated["client_stable"] == "F:/DayZ"
    assert migrated["server_stable"] == "F:/DayZServer"
    assert migrated["hide_server_window"] is True
    assert migrated["last_preset"] == "Default"
    assert migrated["last_mod_preset"] == "Modded"
    preset = json.loads(next(presets_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert preset["profiles"] == "profiles"
    assert preset["server_ip"] == "192.168.1.10"
    assert preset["clean_logs"] is True
    assert preset["mods"] == ["@CF"]
    assert preset["server_mods"] == ["@ServerOnly"]
    assert "filePatching" not in preset["params_server"]
    assert (tmp_path / "config.v2.kr-base.backup.json").is_file()
    assert not migration.migrate_legacy_v2()
