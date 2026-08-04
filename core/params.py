"""Справочник параметров запуска DayZ.

Каждый параметр знает: к кому применим (server/client/both), тип,
работает ли только с DayZDiag, и ключ подсказки для i18n.
UI строит форму по этому справочнику; в пресете хранятся только
явно выставленные значения.
"""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import tr

SERVER = "server"
CLIENT = "client"
BOTH = "both"

FLAG = "flag"  # булев: -noPause
SWITCH = "switch"  # булев со значением: -filePatching=1 / -battleye=0
INT = "int"
STR = "str"


@dataclass(frozen=True)
class ParamSpec:
    name: str  # имя ключа без дефиса, как в командной строке
    target: str  # SERVER / CLIENT / BOTH
    ptype: str
    diag_only: bool = False
    default: object = None

    def tooltip(self) -> str:
        return tr(f"param.{self.name}", _TOOLTIPS_RU.get(self.name, self.name))

    def to_arg(self, value: object) -> str | None:
        if value is None or value == "":
            return None
        if self.ptype == FLAG:
            return f"-{self.name}" if value else None
        if self.ptype == SWITCH:
            # SWITCH хранит явное значение: False означает "-имя=0", а не "не задан"
            return f"-{self.name}={1 if value else 0}"
        return f"-{self.name}={value}"


PARAMS: list[ParamSpec] = [
    # Сервер
    ParamSpec("doLogs", SERVER, FLAG, default=True),
    ParamSpec("adminLog", SERVER, FLAG),
    ParamSpec("netLog", SERVER, FLAG),
    ParamSpec("freezeCheck", SERVER, FLAG),
    ParamSpec("cpuCount", SERVER, INT),
    ParamSpec("limitFPS", SERVER, INT),
    ParamSpec("storage", SERVER, STR),
    ParamSpec("BEpath", SERVER, STR),
    # Оба
    ParamSpec("filePatching", BOTH, SWITCH),
    ParamSpec("noPause", BOTH, FLAG, default=True),
    ParamSpec("battleye", BOTH, SWITCH, diag_only=True),
    ParamSpec("newErrorsAreWarnings", BOTH, SWITCH, diag_only=True),
    ParamSpec("scrDef", BOTH, STR, diag_only=True),
    ParamSpec("doActionLog", BOTH, FLAG, diag_only=True),
    # Клиент
    ParamSpec("password", CLIENT, STR),
    ParamSpec("name", CLIENT, STR),
    ParamSpec("window", CLIENT, FLAG),
]

# Единый отладочный набор. Используется редактором, мастером и генератором
# команд, чтобы Diag-пресет всегда получал одинаковые безопасные значения.
_DEFAULT_SERVER = {
    "doLogs": True,
    "adminLog": True,
    "netLog": True,
    "noPause": True,
}
_DEFAULT_CLIENT = {
    "noPause": True,
    "window": True,
}
_DEFAULT_DIAG = {
    "filePatching": True,
    "battleye": False,
    "newErrorsAreWarnings": True,
}


def default_params(target: str, diag: bool) -> dict[str, object]:
    """Стандартные параметры для нового или неполного пресета."""
    values: dict[str, object] = dict(_DEFAULT_SERVER if target == SERVER else _DEFAULT_CLIENT)
    if diag:
        values.update(_DEFAULT_DIAG)
    return values


_TOOLTIPS_RU = {
    "doLogs": "Включает запись логов сервера (RPT, script.log) в папку профиля.",
    "adminLog": "Пишет лог административных действий и попаданий (ADM-файл).",
    "netLog": "Включает лог сетевого трафика. Нужен редко, замедляет сервер.",
    "freezeCheck": "Следит за зависаниями сервера и пишет дамп при фризе.",
    "cpuCount": "Число ядер CPU, которые разрешено использовать серверу.",
    "limitFPS": "Ограничение FPS серверного цикла, максимум 200 (снижает нагрузку на CPU).",
    "storage": "Своя корневая папка для storage (persistence-файлы).",
    "BEpath": "Свой путь к файлам BattlEye.",
    "filePatching": "Разрешает загружать распакованные файлы (сорсы) поверх PBO. "
    "Обязателен для отладки без запаковки. Diag-сборки обычно требуют 1.",
    "noPause": "Не ставить игру на паузу, когда окно свёрнуто/не в фокусе.",
    "battleye": "Включение/выключение BattlEye. Для Diag и локальной разработки ставьте 0 (выключен).",
    "newErrorsAreWarnings": "Новые ошибки скриптов считаются предупреждениями — игра не падает на них (только Diag).",
    "scrDef": "Определения препроцессора для скриптов, например BITWISEDEBUG (только Diag).",
    "doActionLog": "Подробный лог действий персонажа (только Diag).",
    "password": "Пароль сервера, если задан в serverDZ.cfg (password).",
    "name": "Имя персонажа клиента.",
    "window": "Запуск клиента в оконном режиме.",
}


def specs_for(target: str, diag: bool) -> list[ParamSpec]:
    """Параметры, применимые к цели (server/client) в данном режиме."""
    out = []
    for s in PARAMS:
        if s.target != target and s.target != BOTH:
            continue
        if s.diag_only and not diag:
            continue
        out.append(s)
    return out


def by_name(name: str) -> ParamSpec | None:
    for s in PARAMS:
        if s.name == name:
            return s
    return None
