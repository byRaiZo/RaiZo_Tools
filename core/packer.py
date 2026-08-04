"""Совместимый с KR_QTS фасад собственного PBO Builder byRaiZo."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from .mods import ModInfo
from .pbobuilder.build import build_all
from .pbobuilder.constants import DEFAULT_EXCLUDE_PATTERNS, DEFAULT_PROJECT_ROOT
from .pbobuilder.errors import BuildError
from .pbobuilder.models import BuildConfig
from .pbobuilder.system import (
    get_app_data_dir,
    get_default_max_processes,
    get_logs_dir,
)
from .settings import Settings

_IGNORE_SUFFIXES = {".meta", ".txa", ".bak", ".tmp"}


def _newest_mtime(directory: Path, newer_than: float | None = None) -> float:
    """Самый свежий mtime полезного файла в дереве."""
    newest = 0.0
    stack = [str(directory)]
    while stack:
        try:
            entries = os.scandir(stack.pop())
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    if Path(entry.name).suffix.lower() in _IGNORE_SUFFIXES:
                        continue
                    newest = max(newest, entry.stat().st_mtime)
                    if newer_than is not None and newest > newer_than:
                        return newest
                except OSError:
                    continue
    return newest


def native(path: str | Path) -> str:
    return str(Path(path))


def pbo_for_source(mod: ModInfo, source_dir: str) -> Path:
    return Path(mod.path) / "addons" / f"{Path(source_dir).name}.pbo"


def stale_sources(mod: ModInfo) -> list[str]:
    out: list[str] = []
    for source in mod.sources:
        source_path = Path(source)
        if not source_path.is_dir():
            continue
        output = pbo_for_source(mod, source)
        if not output.is_file():
            out.append(source)
            continue
        if _newest_mtime(source_path, output.stat().st_mtime) > output.stat().st_mtime:
            out.append(source)
    return out


def stale_mods(mods: list[ModInfo]) -> list[tuple[ModInfo, list[str]]]:
    out: list[tuple[ModInfo, list[str]]] = []
    for mod in mods:
        if mod.can_have_sources and mod.sources:
            stale = stale_sources(mod)
            if stale:
                out.append((mod, stale))
    return out


def clean_meta(source_dir: Path) -> int:
    """Оставлено для API-совместимости; PBO Builder не меняет исходники."""
    del source_dir
    return 0


def _tool(root: str, *relative_candidates: str) -> str:
    base = Path(root)
    for relative in relative_candidates:
        candidate = base / relative
        if candidate.is_file():
            return str(candidate)
    return str(base / relative_candidates[0]) if root else ""


def _configured_tool(explicit: str, root: str, *relative_candidates: str) -> str:
    return explicit.strip() or _tool(root, *relative_candidates)


def _project_root(source: Path) -> str:
    anchor = source.resolve().anchor
    return anchor.rstrip("\\/") or str(source.resolve().parent)


def build_config(
    settings: Settings,
    source_root: str | Path,
    output_root: str | Path,
    selected_addons: tuple[str, ...],
    *,
    output_server_root: str | Path = "",
    project_root: str | Path = "",
    pbo_name: str = "",
    force_rebuild: bool | None = None,
    log_file: str | Path = "",
) -> BuildConfig:
    """Создаёт конфигурацию общего PBO backend для GUI и менеджера модов."""
    tools = settings.dayz_tools
    max_processes = settings.pack_max_processes or get_default_max_processes()
    source = Path(source_root)
    return BuildConfig(
        source_root=str(source),
        output_root_dir=str(Path(output_root)),
        output_server_root_dir=str(Path(output_server_root or output_root)),
        temp_dir=settings.pack_temp_dir.strip() or str(get_app_data_dir() / "temp"),
        use_binarize=settings.pack_use_binarize,
        protect_p3d=settings.pack_protect_p3d,
        convert_config=settings.pack_convert_config,
        sign_pbos=settings.pack_sign_pbos,
        force_rebuild=settings.pack_engine == "full" if force_rebuild is None else force_rebuild,
        preflight_before_build=settings.pack_preflight,
        max_processes=max(1, min(int(max_processes), 64)),
        binarize_exe=_configured_tool(settings.pack_binarize_exe, tools, "Bin/Binarize/binarize.exe"),
        cfgconvert_exe=_configured_tool(settings.pack_cfgconvert_exe, tools, "Bin/CfgConvert/CfgConvert.exe"),
        p3d_obfuscator_exe=settings.pack_p3d_obfuscator_exe.strip(),
        dssignfile_exe=_configured_tool(
            settings.pack_dssignfile_exe,
            tools,
            "Bin/DSUtils/DSSignFile.exe",
            "Bin/DSSignFile/DSSignFile.exe",
        ),
        private_key=settings.pack_private_key,
        project_root=str(project_root) if project_root else _project_root(source),
        pbo_name=pbo_name,
        exclude_patterns=settings.pack_exclude_patterns or DEFAULT_EXCLUDE_PATTERNS,
        selected_addons=selected_addons,
        external_validator_exe=_tool(
            tools,
            "Bin/BankRev/BankRev.exe",
            "Bin/BankRev.exe",
        ),
        log_file=str(log_file),
        preflight_checks=dict(settings.pack_preflight_checks),
    )


def _builder_settings(settings: Settings, mod: ModInfo, source: Path) -> BuildConfig:
    return build_config(
        settings,
        source.parent,
        mod.path,
        (source.name,),
        project_root=settings.pbo_last_project_root.strip() or DEFAULT_PROJECT_ROOT,
    )


def pack_source(settings: Settings, mod: ModInfo, source_dir: str) -> tuple[bool, str]:
    """Собирает один addon ядром PBO Builder byRaiZo."""
    source = Path(source_dir)
    if not source.is_dir():
        return False, f"Папка исходников не найдена: {source}"

    log_lines: list[str] = []
    log_path = get_logs_dir() / f"{source.name}.packing.log"

    def log(message: object) -> None:
        log_lines.append(str(message))

    try:
        build_settings = _builder_settings(settings, mod, source)
        build_settings = replace(build_settings, log_file=str(log_path))
        build_all(build_settings, log, lambda _done, _total: None)
    except (BuildError, OSError, ValueError, RuntimeError) as exc:
        log_lines.append(str(exc))
        ok = False
    except Exception as exc:  # noqa: BLE001 — ошибка должна попасть в GUI
        log_lines.append(f"{type(exc).__name__}: {exc}")
        ok = False
    else:
        ok = pbo_for_source(mod, source_dir).is_file()
        if not ok:
            log_lines.append(f"PBO не появился: {pbo_for_source(mod, source_dir)}")

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(log_lines), encoding="utf-8")
    except OSError:
        pass
    return ok, "" if ok else "\n".join(log_lines[-80:])


def pack_source_auto(settings: Settings, mod: ModInfo, source_dir: str) -> tuple[bool, str]:
    return pack_source(settings, mod, source_dir)
