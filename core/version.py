"""Версия приложения — одна на весь проект.

Отсюда её берут окно «О программе», инсталлятор и проверка обновлений.
Формат — MAJOR.MINOR.PATCH, как в тегах релизов на GitHub (`v1.2.3`):
сравнение версий разбирает именно числа, а не строку целиком, иначе «0.10»
оказалась бы старше «0.9».
"""

from __future__ import annotations

VERSION = "1.0.3"
APP_NAME = "RaiZo Tools"
PUBLISHER = "byRaiZo"


def parse(text: str) -> tuple[int, ...]:
    """«v1.2.3» -> (1, 2, 3). Нечисловые куски отбрасываются.

    Пустой или мусорный ввод даёт (0,) — такая версия заведомо не новее любой
    настоящей, и проверка обновлений на битом ответе просто промолчит.
    """
    nums = []
    for part in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        if not digits:
            break
        nums.append(int(digits))
    return tuple(nums) or (0,)


def is_newer(remote: str, local: str = VERSION) -> bool:
    return parse(remote) > parse(local)
