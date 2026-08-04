"""Синхронизация en/de со стрингтейблом ru.json.

Удаляет из en.json/de.json ключи, которых больше нет в ru.json,
и перечисляет ключи, для которых не хватает перевода.
Запуск: python tools/sync_translations.py
"""

import json
from pathlib import Path

LANG = Path(__file__).resolve().parent.parent / "lang"

ru = json.loads((LANG / "ru.json").read_text(encoding="utf-8"))

for code in ("en", "de"):
    f = LANG / f"{code}.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    extra = sorted(set(data) - set(ru))
    missing = sorted(set(ru) - set(data))
    for k in extra:
        del data[k]
    f.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{code}: удалено лишних {len(extra)} {extra}")
    print(f"{code}: не хватает {len(missing)} {missing}")
