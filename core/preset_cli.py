"""CLI запуска и остановки DayZ по имени пресета."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from dataclasses import replace

from . import i18n
from .launch_control import (
    find_preset,
    prepare_launch,
    preset_status,
    select_target,
    start_preset,
    stop_preset,
)
from .migration import migrate_legacy_v2
from .mods import ModRegistry
from .preflight import CRITICAL
from .settings import EXPERIMENTAL, STABLE, Settings

COMMAND_NAMES = {"server", "preset"}


def is_preset_cli_invocation(argv: list[str]) -> bool:
    return bool(argv) and argv[0].lower() in COMMAND_NAMES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="RaiZoTools.exe server",
        description="Запуск и остановка DayZ по сохранённому пресету.",
    )
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--preset", "-p", required=True, help="Имя пресета или имя его JSON-файла")
    parser.add_argument("--target", "-t", choices=("server", "client", "all"), default="all")
    parser.add_argument("--branch", choices=(STABLE, EXPERIMENTAL))
    parser.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-wait", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--show-server-window", action="store_true", help=argparse.SUPPRESS)
    return parser


def _open_console() -> bool:
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32
    if kernel32.GetConsoleWindow() or not kernel32.AllocConsole():
        return False
    kernel32.SetConsoleTitleW("RaiZo Tools — Server CLI")
    sys.stdin = open("CONIN$", encoding="utf-8", errors="ignore")
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    return True


def _wait(created_console: bool, enabled: bool) -> None:
    if created_console and enabled:
        try:
            input("\nНажмите Enter, чтобы закрыть окно...")
        except (EOFError, OSError):
            pass


def run_preset_cli(argv: list[str] | None = None) -> int:
    raw = list(argv or ())
    command_args = raw[1:] if raw and raw[0].lower() in COMMAND_NAMES else raw
    quiet = "--quiet" in command_args
    created_console = False if quiet else _open_console()
    if quiet:
        # У GUI-сборки console=False потоки равны None. Ярлык должен работать
        # без чёрного окна и без падения на первом print().
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
    should_wait = "--no-wait" not in command_args
    parser = build_parser()
    try:
        args = parser.parse_args(command_args)
        migrate_legacy_v2()
        settings = Settings.load()
        if args.show_server_window or (args.quiet and args.action == "start"):
            # Ярлык — самостоятельный способ запуска. Глобальная GUI-галка
            # «Скрыть окно» к нему не относится и на диск не перезаписывается.
            # Проверка quiet сохраняет совместимость с уже созданными ярлыками,
            # в которых ещё нет явного --show-server-window.
            settings = replace(settings, hide_server_window=False)
        i18n.load(settings.language)
        preset = select_target(find_preset(args.preset), args.target)
        branch = args.branch or preset.branch
        registry = ModRegistry(settings)
        registry.scan()

        if args.action == "start":
            problems = prepare_launch(preset, settings, branch, registry)
            for problem in problems:
                prefix = "ОШИБКА" if problem.severity == CRITICAL else "ПРЕДУПРЕЖДЕНИЕ"
                print(f"{prefix}: {problem.message}")
            if any(problem.severity == CRITICAL for problem in problems):
                return 2
            error = start_preset(
                preset,
                settings,
                branch,
                registry,
                lambda text, _level: print(text),
                force_restart=args.quiet,
            )
            if error:
                print(f"ОШИБКА: {error}", file=sys.stderr)
                return 1
            print(f"Запущено: {args.target}, пресет «{preset.name}».")
            return 0

        if args.action == "stop":
            stopped = stop_preset(preset, settings, branch, registry, force=args.quiet)
            print(f"Остановлено процессов: {stopped}.")
            return 0

        state = preset_status(preset, settings, branch, registry)
        for kind, pids in state.items():
            print(f"{kind}: {', '.join(map(str, pids)) if pids else 'stopped'}")
        return 0
    except (OSError, ValueError) as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1
    finally:
        _wait(created_console, should_wait)
