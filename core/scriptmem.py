"""Скриптовая память слоёв DayZ и счётчик ошибок — из RPT сервера/клиента.

При компиляции каждого слоя движок пишет в RPT одну строку с расходом
статической памяти:

    SCRIPT : Module: World; loaded 2123x files; 5629x classes;
             used 10807/33554 kB (32) of static memory; defines: "..."

Число в скобках — тот же процент, но округлённый вниз до целого: 99.7%
показалось бы как «99». Считаем процент сами из used/total, иначе у самой
границы, где это важнее всего, картина врёт.

Лимит слоя жёсткий: если скрипты в него не влезли, слой не скомпилируется и
сервер не поднимется вовсе. Поэтому запас по памяти — то, что нужно видеть до
падения, а не после.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Имя модуля в RPT -> имя папки слоя в scripts\, как их называют мододелы.
# Показываем именно второе: в модах правят «5_Mission», а не «Mission».
MODULES = {
    "GameLib": "2_GameLib",
    "Game": "3_Game",
    "World": "4_World",
    "Mission": "5_Mission",
}
LAYERS = list(MODULES.values())

# Слой, по которому судят о готовности стороны: 5_Mission компилируется
# последним, и до него дело доходит только когда всё остальное уже поднялось.
# Живой процесс этого не заменяет — он появляется задолго до готовности.
READY_LAYER = "5_Mission"

# «$CurrentDir:...init.c» — тоже Module-строка, но это разовая компиляция
# init.c миссии со своим маленьким лимитом, к слоям отношения не имеет:
# ловим только известные имена.
_LINE_RE = re.compile(r"Module:\s*(?P<name>\w+);.*?used\s+(?P<used>\d+)\s*/\s*(?P<total>\d+)\s*kB", re.IGNORECASE)

DANGER_PCT = 95.0  # выше — предупреждаем крупно: запаса почти не осталось
LIMIT_PCT = 100.0  # достигнут — слой не соберётся

# Пороги для цвета. До 60 — норма, 60-85 — средне, дальше — плохо; между
# опорными точками цвет переходит плавно, чтобы 84% и 86% не выглядели как
# два разных мира.
_OK_PCT, _MID_PCT = 60.0, 85.0
_GREEN = (76, 175, 80)
_YELLOW = (229, 192, 123)
_RED = (255, 82, 82)


@dataclass(frozen=True)
class Usage:
    """Расход памяти одного слоя."""

    layer: str  # 2_GameLib | 3_Game | 4_World | 5_Mission
    used_kb: int
    total_kb: int

    @property
    def percent(self) -> float:
        return 100.0 * self.used_kb / self.total_kb if self.total_kb else 0.0

    @property
    def over_limit(self) -> bool:
        return self.percent >= LIMIT_PCT

    @property
    def dangerous(self) -> bool:
        return self.percent >= DANGER_PCT


def parse(line: str) -> Usage | None:
    """Usage по строке RPT либо None, если строка не про слой."""
    m = _LINE_RE.search(line)
    if not m:
        return None
    layer = MODULES.get(m.group("name"))
    if not layer:
        return None
    return Usage(layer=layer, used_kb=int(m.group("used")), total_kb=int(m.group("total")))


def _mix(a: tuple, b: tuple, t: float) -> str:
    t = min(1.0, max(0.0, t))
    return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * t):02x}" for i in range(3))


def color(pct: float) -> str:
    """Цвет процента: зелёный -> жёлтый -> красный без резких скачков."""
    if pct <= _OK_PCT:
        return _mix(_GREEN, _GREEN, 0)
    if pct <= _MID_PCT:
        return _mix(_GREEN, _YELLOW, (pct - _OK_PCT) / (_MID_PCT - _OK_PCT))
    return _mix(_YELLOW, _RED, (pct - _MID_PCT) / (LIMIT_PCT - _MID_PCT))
