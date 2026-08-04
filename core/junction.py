"""Создание junction-ссылок на папки — одной функцией на весь проект.

Раньше junction создавались запуском `cmd /c mklink /J <ссылка> <цель>`. Так
делают все, и это дыра: cmd разбирает командную строку заново, а Python
берёт аргумент в кавычки, только если в нём есть пробел. Путь без пробелов,
но со знаком `&`, разваливается на две команды, и вторая выполняется:

    mklink /J C:\\...\\MODS\\@x&whoami>C:\\...\\out.txt C:\\...\\target
                             ^ здесь cmd заканчивает первую команду

Достижимо это не теоретически: имя папки мода собирается из `name` в его
meta.cpp, а meta.cpp пишет автор мода в Workshop. Санитайзер `folder_name`
чистит символы, недопустимые в именах Windows (`<>:"/\\|?*`), — но `&`, `^`,
`%` и скобки в именах допустимы и проходят насквозь.

CreateJunction зовёт Windows напрямую: разбирать нечего, инъекции неоткуда
взяться, а заодно нет запуска процесса — 0.3 мс вместо 24.
"""

from __future__ import annotations

from pathlib import Path


def create(link: Path, target: Path) -> str:
    """Создаёт junction. Пустая строка — успех, иначе текст ошибки."""
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, AttributeError):
        return "junction не поддерживается этой сборкой Python"
    except OSError as e:
        return str(e)
    return ""
