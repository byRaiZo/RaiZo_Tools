"""Headless-управление сервером и клиентом по сохранённому пресету."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from .command_lock import process_command_lock
from .launcher import LaunchWorker, matching_processes, stop_processes
from .mods import ModRegistry
from .preflight import CRITICAL, Problem, run_checks
from .presets import ServerPreset
from .settings import Settings

TARGETS = {"server", "client", "all"}


def find_preset(name: str, presets: list[ServerPreset] | None = None) -> ServerPreset:
    """Находит пресет по имени либо уникальному имени файла без ``.json``."""
    available = presets if presets is not None else ServerPreset.load_all()
    wanted = name.strip().casefold()
    by_file = [preset for preset in available if preset.file_stem().casefold() == wanted]
    if len(by_file) == 1:
        return by_file[0]
    by_name = [preset for preset in available if preset.name.casefold() == wanted]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        variants = ", ".join(preset.file_stem() for preset in by_name)
        raise ValueError(f"Имя пресета неоднозначно. Укажите одно из: {variants}")
    raise ValueError(f"Пресет не найден: {name}")


def select_target(preset: ServerPreset, target: str) -> ServerPreset:
    """Создаёт временную копию пресета с нужными ролями запуска."""
    if target not in TARGETS:
        raise ValueError(f"Неизвестная цель: {target}")
    return replace(
        preset,
        launch_server=target in {"server", "all"},
        launch_client=target in {"client", "all"},
    )


def prepare_launch(
    preset: ServerPreset,
    settings: Settings,
    branch: str,
    registry: ModRegistry,
) -> list[Problem]:
    """Проводит ту же проверку и подготовку CFG/профиля, что главное окно."""
    problems = run_checks(preset, settings, branch, registry)
    if any(problem.severity == CRITICAL for problem in problems):
        return problems

    from .layout import resolve_config, resolve_profiles

    cfg_path = resolve_config(preset.server_config, settings, branch, preset.mode)
    if preset.launch_server and cfg_path and Path(cfg_path).is_file():
        from .servercfg import sync_mission_for_launch

        sync_mission_for_launch(Path(cfg_path), preset.mission)

    profiles = resolve_profiles(preset.profiles, settings, branch, preset.mode)
    if profiles:
        Path(profiles).mkdir(parents=True, exist_ok=True)
    return problems


def start_preset(
    preset: ServerPreset,
    settings: Settings,
    branch: str,
    registry: ModRegistry,
    log: Callable[[str, str], None] | None = None,
    *,
    force_restart: bool = False,
) -> str:
    """Запускает выбранные роли синхронно; пустая строка означает успех."""
    worker = LaunchWorker(preset, settings, branch, registry, force_restart=force_restart)
    if log is not None:
        worker.log.connect(log)
    return worker.run_blocking()


def stop_preset(
    preset: ServerPreset,
    settings: Settings,
    branch: str,
    registry: ModRegistry,
    *,
    force: bool = False,
) -> int:
    """Останавливает только процессы, точно совпавшие с пресетом и ролями."""
    kinds = {kind for kind, enabled in (("server", preset.launch_server), ("client", preset.launch_client)) if enabled}
    with process_command_lock():
        return stop_processes(matching_processes(preset, settings, branch, registry, kinds), force=force)


def preset_status(
    preset: ServerPreset,
    settings: Settings,
    branch: str,
    registry: ModRegistry,
) -> dict[str, list[int]]:
    """Возвращает PID точных совпадений отдельно для сервера и клиента."""
    result: dict[str, list[int]] = {}
    for kind in ("server", "client"):
        if (kind == "server" and not preset.launch_server) or (kind == "client" and not preset.launch_client):
            continue
        result[kind] = [proc.pid for proc in matching_processes(preset, settings, branch, registry, {kind})]
    return result
