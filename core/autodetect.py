"""Автопоиск путей Steam, DayZ и DayZ Tools.

Основной источник — манифесты Steam (core.steam_state): там лежит точное имя
папки установки и признак «установлено полностью». Поиск по именам папок
оставлен запасным вариантом — на случай ручной установки мимо Steam или
повреждённого манифеста.
"""

from __future__ import annotations

from pathlib import Path

from core import steam_state
from core.steam_urls import (
    APP_DAYZ,
    APP_DAYZ_EXP,
    APP_DAYZ_EXP_SERVER,
    APP_DAYZ_SERVER,
    APP_DAYZ_TOOLS,
    APP_DAYZ_TOOLS_EXP,
)

# Имена папок установок в steamapps/common — запасной путь поиска
CLIENT_STABLE_DIRS = ("DayZ",)
CLIENT_EXP_DIRS = ("DayZ Exp", "DayZ Experimental")
SERVER_STABLE_DIRS = ("DayZServer", "DayZ Server")
SERVER_EXP_DIRS = ("DayZ Server Exp", "DayZ Experimental Server")
DAYZ_TOOLS_DIRS = ("DayZ Tools",)
DAYZ_TOOLS_EXP_DIRS = ("DayZ Experimental Tools", "DayZ Tools Exp")

DAYZ_APPID = APP_DAYZ

# поле настроек -> (appid, имена папок, файл-маркер внутри)
_STEAM_PATHS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "client_stable": (APP_DAYZ, CLIENT_STABLE_DIRS, "DayZ_x64.exe"),
    "client_exp": (APP_DAYZ_EXP, CLIENT_EXP_DIRS, "DayZ_x64.exe"),
    "server_stable": (APP_DAYZ_SERVER, SERVER_STABLE_DIRS, "DayZServer_x64.exe"),
    "server_exp": (APP_DAYZ_EXP_SERVER, SERVER_EXP_DIRS, "DayZServer_x64.exe"),
    "dayz_tools": (APP_DAYZ_TOOLS, DAYZ_TOOLS_DIRS, ""),
    "dayz_tools_exp": (APP_DAYZ_TOOLS_EXP, DAYZ_TOOLS_EXP_DIRS, ""),
}


def steam_root() -> Path | None:
    return steam_state.steam_root()


def steam_libraries() -> list[Path]:
    """Все Steam-библиотеки (папки, содержащие steamapps)."""
    return steam_state.libraries()


def _find_by_name(names: tuple[str, ...], exe: str) -> str:
    """Запасной поиск: перебор известных имён папок в steamapps/common."""
    for lib in steam_libraries():
        common = lib / "steamapps" / "common"
        for name in names:
            p = common / name
            if (p / exe).is_file() if exe else p.is_dir():
                return str(p)
    return ""


def detect_path(key: str) -> str:
    """Путь установки для поля настроек; пусто — не найдено.

    Сначала манифест Steam (знает точное имя папки и то, что установка
    завершена), затем перебор известных имён папок.
    """
    entry = _STEAM_PATHS.get(key)
    if not entry:
        return ""
    appid, names, exe = entry

    st = steam_state.app_state(appid)
    if st is not None and st.installed:
        return st.path

    # DayZ Tools внутри лежит без единого предсказуемого exe — хватает папки
    found = _find_by_name(names, exe)
    if found:
        return found
    if exe:
        # exe не нашёлся, но папка есть — например, установка ещё не завершена
        return ""
    return ""


def detect_workshop_dirs() -> list[str]:
    return steam_state.workshop_state(DAYZ_APPID).content_dirs


def detect_all(refresh: bool = True) -> dict:
    """Возвращает найденные пути; пустая строка/список — не найдено.

    refresh перечитывает список библиотек: автопоиск обычно запускают именно
    после того, как что-то доустановили — возможно, в новую библиотеку.
    """
    if refresh:
        steam_state.libraries(refresh=True)
    res: dict = {key: detect_path(key) for key in _STEAM_PATHS}
    res["workshop_dirs"] = detect_workshop_dirs()
    return res
