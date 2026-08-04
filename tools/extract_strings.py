"""Генерирует lang/ru.json из исходников: собирает все tr("key", "default").

Запуск: python tools/extract_strings.py
Русские строки — эталон (дефолты в коде); en.json/de.json переводятся от них.
"""

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

strings: dict[str, str] = {}

for py in list((ROOT / "core").glob("*.py")) + list((ROOT / "ui").glob("*.py")) + [ROOT / "main.py"]:
    tree = ast.parse(py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "tr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[1], ast.Constant)
        ):
            key = node.args[0].value
            value = node.args[1].value
            if isinstance(key, str) and isinstance(value, str):
                strings[key] = value

# Динамические ключи: подсказки параметров запуска и переменных cfg
from core.params import _TOOLTIPS_RU  # noqa: E402 — после настройки sys.path выше

for name, text in _TOOLTIPS_RU.items():
    strings[f"param.{name}"] = text

cfg_text = (ROOT / "ui" / "cfg_editor.py").read_text(encoding="utf-8")
m = re.search(r"_HINTS_RU\s*=\s*\{(.*?)\n\}", cfg_text, re.DOTALL)
if m:
    for mm in re.finditer(r'"(\w+)":\s*"((?:[^"\\]|\\.)*)"', m.group(1)):
        strings[f"cfgvar.{mm.group(1)}"] = mm.group(2).replace('\\"', '"')

out = ROOT / "lang" / "ru.json"
out.write_text(json.dumps(dict(sorted(strings.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"lang/ru.json: {len(strings)} keys")
