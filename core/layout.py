"""Рабочая структура RaiZo Tools в корне DayZ Server.

DayZServer/
├── serverDZ*.cfg
├── profiles/
├── mpmissions/
├── MODS/
└── keys/

Приложение автоматически создаёт только MODS. Конфиги, профили, миссии и
persistence остаются пользовательскими данными и никогда не удаляются вместе
с пресетом.
"""

from __future__ import annotations

import re
from pathlib import Path

from .settings import Settings, APP_DIR, RES_DIR

PROFILE_SUBDIR = "profiles"
MISSIONS_SUBDIR = "mpmissions"
MODS_SUBDIR = "MODS"  # junction-ссылки на подключаемые моды
MODS_DL_SUBDIR = "mods_dl"  # скачанные с GitHub моды (реальные файлы)

TEMPLATE_CFG = RES_DIR / "data" / "serverDZ_template.cfg"

# Первый символ — только буква: имя пресета уходит в имена папок миссии и
# профиля, в имя конфига и дальше в конфиг сервера, а идентификатор,
# начинающийся с цифры или знака, — источник проблем.
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")

# actual.* — шаблоны карт; имя пресета не должно с ними пересекаться
RESERVED_NAMES = {"actual"}


def valid_name(name: str) -> bool:
    """Только латиница, цифры, дефис и подчёркивание — никакой кириллицы.
    Первым символом — только буква."""
    return bool(_NAME_RE.fullmatch(name or ""))


def name_conflict(name: str, world: str = "", current_key: str = "") -> str:
    """Возвращает текст проблемы с финальным именем пресета или пустую строку.

    Одно имя на разных картах допустимо (финальные имена различаются
    суффиксом карты); дубликат пары имя+карта — нет. Сравнение без учёта
    регистра: файловая система Windows не различает Test и test.
    """
    from .i18n import tr
    from .presets import ServerPreset

    low = (name or "").lower()
    if low in RESERVED_NAMES:
        return tr("preset.name_reserved", "Имя «{n}» зарезервировано под шаблоны карт.", n=name)
    key = f"{low}|{(world or '').lower()}"
    for other in ServerPreset.load_all():
        other_key = f"{other.name.lower()}|{other.world.lower()}"
        if other_key == key and other_key != current_key.lower():
            return tr("preset.name_taken", "Пресет «{n}» для этой карты уже существует.", n=other.name)
    return ""


def preset_key(name: str, world: str) -> str:
    return f"{(name or '').lower()}|{(world or '').lower()}"


def mode_root(settings: Settings, branch: str, mode: str) -> str:
    del mode
    return settings.server_root(branch)


def debug_dir(settings: Settings, branch: str, mode: str) -> Path:
    """Совместимое имя API: теперь возвращает сам корень DayZ Server."""
    root = mode_root(settings, branch, mode)
    return Path(root) if root else Path("")


def ensure_layout(base: Path) -> None:
    """Создаёт только безопасный junction-хаб модов."""
    (base / MODS_SUBDIR).mkdir(parents=True, exist_ok=True)


def mods_link_dir(root: str) -> Path:
    return Path(root) / MODS_SUBDIR


def downloads_base(settings: Settings) -> Path:
    return Path(settings.downloads_dir) if settings.downloads_dir else APP_DIR / "downloads"


def mods_dl_dir(settings: Settings) -> Path:
    """Единое хранилище скачанных модов — общее для всех клиентов и серверов.

    В DayZ Server моды попадают junction-ссылками через MODS.
    """
    return downloads_base(settings) / "mods"


# ------------------------------------------------------------- резолв путей


def _resolve(value: str, settings: Settings, branch: str, mode: str, subdir: str) -> str:
    """Голое имя -> DayZServer/<subdir>/<имя>; абсолютный путь не меняется."""
    if not value:
        return ""
    p = Path(value)
    if p.is_absolute():
        return str(p)
    if len(p.parts) == 1:
        base = debug_dir(settings, branch, mode)
        if str(base):
            return str(base / subdir / value) if subdir else str(base / value)
    return str(Path(settings.server_root(branch)) / p)


def resolve_config(value: str, settings: Settings, branch: str, mode: str) -> str:
    return _resolve(value, settings, branch, mode, "")


def resolve_profiles(value: str, settings: Settings, branch: str, mode: str) -> str:
    del value
    return _resolve(PROFILE_SUBDIR, settings, branch, mode, "")


def resolve_mission(value: str, settings: Settings, branch: str, mode: str) -> str:
    return _resolve(value, settings, branch, mode, MISSIONS_SUBDIR)


# ------------------------------------------------------------- создание файлов


def preset_base_name(name: str, mission_name: str = "") -> str:
    """Имя файлов пресета: <имя>_<карта> (карта — суффикс миссии)."""
    world = mission_name.rsplit(".", 1)[1] if "." in mission_name else ""
    return f"{name}_{world}" if world else name


TEST_SUFFIX = "TEST"


def server_display_name(prefix: str, preset_name: str) -> str:
    """Название сервера для hostname: «[префикс] имя пресета TEST».

    TEST дописывается всегда. Раньше стояла защита от дубля — не дописывать,
    если слово уже есть в префиксе или имени, — и она же всё ломала: проверка
    шла по подстроке, а пресет с именем «test» здесь скорее правило, чем
    исключение. Выходило «[KR] test» вместо «[KR] test TEST», причём молча и
    только у части пресетов.

    Предсказуемость важнее аккуратности редкого случая: «[KR TEST] my TEST»
    выглядит избыточно, но человек хотя бы знает, что получит.
    """
    prefix, preset_name = prefix.strip(), preset_name.strip()
    parts = []
    if prefix:
        parts.append(f"[{prefix}]")
    if preset_name:
        parts.append(preset_name)
    parts.append(TEST_SUFFIX)
    return " ".join(parts)


def server_configs(settings: Settings, branch: str, mode: str) -> list[str]:
    """CFG-файлы, доступные в корне DayZ Server."""
    base = debug_dir(settings, branch, mode)
    if not str(base) or not base.is_dir():
        return []
    return [
        path.name
        for path in sorted(
            base.glob("*.cfg"),
            key=lambda path: (path.name.casefold() != "serverdz.cfg", path.name.casefold()),
        )
        if path.is_file()
    ]


def create_server_config(settings: Settings, branch: str, mode: str, name: str, mission_name: str = "") -> str:
    """Создаёт отдельный CFG из шаблона и возвращает его имя.

    Существующий файл никогда не перезаписывается.
    """
    base = debug_dir(settings, branch, mode)
    if not str(base):
        raise RuntimeError("Не задан корень игры/сервера в настройках")
    ensure_layout(base)
    fname = preset_base_name(name, mission_name)

    cfg_name = f"serverDZ_{fname}.cfg"
    cfg_path = base / cfg_name
    if not cfg_path.exists():
        try:
            template = TEMPLATE_CFG.read_text(encoding="utf-8")
        except OSError:
            template = 'hostname = "{NAME}";\n'
        # Название собирается здесь, а не в шаблоне: правило «[префикс] имя
        # TEST» требует проверки, нет ли слова TEST уже в префиксе или имени,
        # а подстановкой в шаблон такое не выразить.
        name_value = server_display_name(settings.project_prefix, name)
        text = template.replace("{NAME}", name_value).replace("{MISSION}", mission_name or "dayzOffline.chernarusplus")
        cfg_path.write_bytes(text.encode("utf-8"))  # UTF-8 без BOM

    return cfg_name


def create_preset_files(
    settings: Settings, branch: str, mode: str, name: str, mission_name: str = ""
) -> tuple[str, str]:
    """Совместимая обёртка для старых вызовов."""
    return (
        create_server_config(settings, branch, mode, name, mission_name),
        PROFILE_SUBDIR,
    )


def rename_preset_files(settings: Settings, branch: str, mode: str, old: str, new: str, world: str) -> None:
    """Переименование записи пресета не переименовывает серверные данные."""
    del settings, branch, mode, old, new, world
