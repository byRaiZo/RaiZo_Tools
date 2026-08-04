"""Переводы: lang/<code>.json с парами "ключ": "текст".

Строки по умолчанию (русские) заданы прямо в коде вторым аргументом tr().
Файл ru.json может переопределять их, en.json/de.json — переводить.
Ключ, которого нет ни в файле, ни в default, показывается как есть.
"""

from __future__ import annotations

import json

from .settings import RES_DIR

LANG_DIR = RES_DIR / "lang"
AVAILABLE = {"ru": "Русский", "en": "English", "de": "Deutsch"}

_strings: dict[str, str] = {}
_code = "ru"


def load(code: str) -> None:
    global _strings, _code
    _code = code if code in AVAILABLE else "ru"
    _strings = {}
    f = LANG_DIR / f"{_code}.json"
    if f.is_file():
        try:
            _strings = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _strings = {}


def current() -> str:
    return _code


def tr(key: str, default: str | None = None, **fmt) -> str:
    s = _strings.get(key)
    if s is None:
        s = default if default is not None else key
    if fmt:
        try:
            s = s.format(**fmt)
        except (KeyError, IndexError):
            pass
    return s
