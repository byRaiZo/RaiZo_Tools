"""Ссылки steam:// — прямые команды клиенту Steam.

Открыть страницу мода прямо в Steam (там сразу есть кнопка «Подписаться»)
или запустить установку компонента DayZ — это делает клиент, а не браузер,
так что пользователю не нужно логиниться на сайте и искать ту же страницу
второй раз.

Если протокол не зарегистрирован (Steam не установлен), функции отдают
обычные https-ссылки — приложение остаётся работоспособным.
"""

from __future__ import annotations

import sys

# appid компонентов DayZ (сверено с appmanifest_*.acf установленной библиотеки)
APP_DAYZ = "221100"
APP_DAYZ_SERVER = "223350"
APP_DAYZ_EXP = "1024020"
APP_DAYZ_EXP_SERVER = "1042420"
APP_DAYZ_TOOLS = "830640"
APP_DAYZ_TOOLS_EXP = "2909700"

# поле настроек -> (appid, человеческое название)
SETTINGS_APPS: dict[str, tuple[str, str]] = {
    "client_stable": (APP_DAYZ, "DayZ"),
    "server_stable": (APP_DAYZ_SERVER, "DayZ Server"),
    "client_exp": (APP_DAYZ_EXP, "DayZ Experimental"),
    "server_exp": (APP_DAYZ_EXP_SERVER, "DayZ Experimental Server"),
    "dayz_tools": (APP_DAYZ_TOOLS, "DayZ Tools"),
    "dayz_tools_exp": (APP_DAYZ_TOOLS_EXP, "DayZ Tools Experimental"),
}

_WORKSHOP_HTTPS = "https://steamcommunity.com/sharedfiles/filedetails/?id={id}"
_STORE_HTTPS = "https://store.steampowered.com/app/{id}"


def protocol_available() -> bool:
    """Зарегистрирован ли обработчик steam:// (то есть установлен ли Steam)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"steam\shell\open\command"):
            return True
    except OSError:
        return False


def workshop_item(item_id: str) -> str:
    """Страница предмета Workshop: в клиенте Steam, иначе в браузере."""
    if protocol_available():
        return f"steam://url/CommunityFilePage/{item_id}"
    return _WORKSHOP_HTTPS.format(id=item_id)


def store_page(appid: str) -> str:
    """Страница приложения в магазине."""
    if protocol_available():
        return f"steam://store/{appid}"
    return _STORE_HTTPS.format(id=appid)


def install(appid: str) -> str:
    """Диалог установки приложения. Без Steam — просто страница магазина."""
    if protocol_available():
        return f"steam://install/{appid}"
    return _STORE_HTTPS.format(id=appid)
