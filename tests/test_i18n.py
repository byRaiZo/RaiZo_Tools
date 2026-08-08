import json
from pathlib import Path


def test_translation_keys_match():
    root = Path(__file__).resolve().parents[1] / "lang"
    files = [root / "ru.json", root / "en.json", root / "de.json"]
    keys = [set(json.loads(path.read_text(encoding="utf-8"))) for path in files]
    assert keys[0] == keys[1] == keys[2]


def test_pbo_builder_name_is_used_in_russian_ui():
    path = Path(__file__).resolve().parents[1] / "lang" / "ru.json"
    strings = json.loads(path.read_text(encoding="utf-8"))
    assert strings["settings.pbo_settings"] == "Общие параметры сборки PBO"
    assert strings["pbo.title"] == "Настройки PBO Builder"
