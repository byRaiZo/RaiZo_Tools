"""Явное удаление persistence выбранной миссии DayZ."""

from __future__ import annotations

import shutil
from pathlib import Path


class StorageWipeError(ValueError):
    """Небезопасная или недоступная цель вайпа."""


def _is_reparse_directory(path: Path) -> bool:
    """Не разрешаем вайп через symlink/junction за пределами миссии."""
    return path.is_symlink() or path.is_junction()


def storage_directories(mission_dir: Path) -> list[Path]:
    """Возвращает только непосредственные папки ``storage_*`` миссии."""
    mission = Path(mission_dir)
    if not mission.is_dir():
        raise StorageWipeError(f"Папка миссии не найдена: {mission}")

    targets: list[Path] = []
    try:
        children = list(mission.iterdir())
    except OSError as error:
        raise StorageWipeError(f"Не удалось прочитать папку миссии: {error}") from error

    for child in children:
        if not child.name.casefold().startswith("storage_") or not child.is_dir():
            continue
        if _is_reparse_directory(child):
            raise StorageWipeError(f"Вайп ссылки запрещён: {child}")
        targets.append(child)
    return sorted(targets, key=lambda path: path.name.casefold())


def wipe_storage(mission_dir: Path) -> int:
    """Удаляет ``storage_*`` выбранной миссии и возвращает число папок."""
    targets = storage_directories(mission_dir)
    for target in targets:
        try:
            shutil.rmtree(target)
        except OSError as error:
            raise StorageWipeError(f"Не удалось удалить {target}: {error}") from error
    return len(targets)
