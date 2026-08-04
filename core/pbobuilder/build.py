from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .errors import BuildError
from .files import (
    copy_source_to_staging,
    ensure_builder_temp_root,
    ensure_config_cpp_files_in_staging,
    ensure_p3d_files_in_staging,
    overlay_tree,
)
from .filters import create_temp_exclude_file, has_p3d_files, parse_exclude_patterns
from .models import (
    BuildConfig,
    BuildJob,
    BuildPaths,
    BuildResult,
    LogCallback,
    ProgressCallback,
    normalized_paths,
)
from .pbo import (
    cleanup_output_work_dir,
    copy_bikey_to_keys,
    create_output_work_dir,
    find_new_signature_for_pbo,
    pack_pbo,
    replace_output_artifacts,
    run_dssignfile,
    verify_packed_pbo,
    verify_published_output,
    wait_for_file_ready,
)
from .preflight import run_preflight_for_targets
from .system import get_available_logical_threads, load_build_cache, save_build_cache
from .targets import (
    compute_addon_state_hash,
    detect_addon_targets,
    format_duration,
    get_addon_temp_root,
    get_pbo_base_name,
    get_pbo_prefix,
)
from .tools import (
    collect_non_binarized_p3ds,
    create_binarize_source_without_odol,
    ensure_all_p3ds_binarized_in_staging,
    run_cfgconvert_rvmats_to_bin,
    run_cfgconvert_to_bin,
    run_dayz_binarize,
    run_dayz_texheaders,
    run_p3d_obfuscator_for_staging,
)


@dataclass(slots=True)
class _BuildContext:
    config: BuildConfig
    settings: dict[str, Any]
    paths: BuildPaths
    exclude_patterns: list[str]
    exclude_file: str
    targets: list[tuple[str, str]]
    cache: dict[str, Any]
    source_cache: dict[str, Any]
    hash_cache: dict[str, Any]
    result: BuildResult


def _prepare_paths(config: BuildConfig, log: LogCallback) -> BuildPaths:
    paths = normalized_paths(config)
    if not os.path.isdir(paths.source_root):
        raise BuildError(f"Source root is not a directory: {paths.source_root}")
    for directory in (
        paths.output_client_addons,
        paths.output_client_keys,
        paths.output_server_addons,
        paths.output_server_keys,
    ):
        os.makedirs(directory, exist_ok=True)
    ensure_builder_temp_root(
        paths.temp_root,
        log,
        paths.source_root,
        paths.output_client_root,
    )
    if paths.output_server_root != paths.output_client_root:
        ensure_builder_temp_root(
            paths.temp_root,
            None,
            paths.source_root,
            paths.output_server_root,
        )
    return paths


def _validate_tools(config: BuildConfig, paths: BuildPaths, log: LogCallback) -> str:
    exclude_file = ""
    if config.use_binarize:
        if not os.path.isfile(config.binarize_exe):
            raise BuildError("binarize.exe not found. Select the DayZ Tools binarize.exe path.")
        log(f"Using binarize.exe: {config.binarize_exe}")
        exclude_file = create_temp_exclude_file(paths.temp_root, config.exclude_patterns, log)
    if config.protect_p3d:
        if not config.use_binarize:
            raise BuildError("P3D protection requires Binarize P3D to be enabled.")
        if not os.path.isfile(config.p3d_obfuscator_exe):
            raise BuildError("P3DObfuscator.exe not found. Select its path.")
    if config.convert_config and not os.path.isfile(config.cfgconvert_exe):
        raise BuildError("CfgConvert.exe not found. Select the DayZ Tools CfgConvert.exe path.")

    needs_signing = config.sign_pbos and any(not name.upper().endswith("_SERVER") for name in config.selected_addons)
    if needs_signing:
        if not os.path.isfile(config.dssignfile_exe):
            raise BuildError("DSSignFile.exe not found. Select the DayZ Tools DSSignFile.exe path.")
        if not os.path.isfile(config.private_key):
            raise BuildError("Private key not found. Select your .biprivatekey file.")
        log(f"Using DSSignFile.exe: {config.dssignfile_exe}")
        log(f"Using private key: {os.path.basename(config.private_key)}")
    elif config.sign_pbos:
        log("Signing enabled, but selected targets are server-only. Signing will be skipped.")
    return exclude_file


def _prepare_build(
    config: BuildConfig,
    log: LogCallback,
    progress: ProgressCallback,
) -> _BuildContext:
    settings = config.as_legacy_dict()
    paths = _prepare_paths(config, log)
    log(f"Output client Addons: {paths.output_client_addons}")
    log(f"Output server Addons: {paths.output_server_addons}")
    log(f"Temporary root:       {paths.temp_root}")
    log("Content-safe cache checks are enabled.")
    log(f"Logical CPU threads: {os.cpu_count() or 'unknown'}")
    log(f"Available threads:   {get_available_logical_threads()}")
    log(f"Binarize processes:  {config.max_processes}")

    exclude_file = _validate_tools(config, paths, log)
    patterns = parse_exclude_patterns(config.exclude_patterns)
    all_targets = detect_addon_targets(paths.source_root, paths.output_client_addons)
    selected = set(config.selected_addons)
    targets = [(name, path) for name, path in all_targets if name in selected]
    if not targets:
        raise BuildError("No addon targets selected.")
    log(f"Found {len(all_targets)} addon target(s); selected {len(targets)}.")

    if config.preflight_before_build:
        preflight = run_preflight_for_targets(settings, targets, log, progress)
        if preflight.errors:
            raise BuildError(f"Preflight failed with {preflight.errors} error(s).")
        log(f"Preflight completed with {preflight.warnings} warning(s).")

    cache = load_build_cache()
    source_cache = cache.setdefault(os.path.abspath(paths.source_root).lower(), {})
    return _BuildContext(
        config=config,
        settings=settings,
        paths=paths,
        exclude_patterns=patterns,
        exclude_file=exclude_file,
        targets=targets,
        cache=cache,
        source_cache=source_cache,
        hash_cache={},
        result=BuildResult(targets=len(targets), log_file=config.log_file),
    )


def _prepare_job(
    context: _BuildContext,
    target: tuple[str, str],
    index: int,
    log: LogCallback,
    progress: ProgressCallback,
) -> BuildJob | None:
    config, paths = context.config, context.paths
    folder_name, folder_path = target
    progress(index - 1, len(context.targets))
    log("")
    log(f"Preparing addon {index}/{len(context.targets)}: {folder_name}")
    pbo_name = get_pbo_base_name(folder_name, config.pbo_name, len(context.targets))
    server_only = folder_name.upper().endswith("_SERVER")
    addons_dir = paths.output_server_addons if server_only else paths.output_client_addons
    keys_dir = paths.output_server_keys if server_only else paths.output_client_keys
    output_pbo = os.path.join(addons_dir, pbo_name + ".pbo")
    prefix = get_pbo_prefix(pbo_name, folder_path)
    state_hash = compute_addon_state_hash(
        folder_path,
        prefix,
        context.settings,
        context.exclude_patterns,
        context.hash_cache,
    )
    sign_output = config.sign_pbos and not server_only
    cache_entry = context.source_cache.get(folder_name, {})
    if (
        not config.force_rebuild
        and cache_entry.get("hash") == state_hash
        and os.path.isfile(output_pbo)
        and (not sign_output or find_new_signature_for_pbo(output_pbo))
    ):
        log(f"Skipping {folder_name}: no changes detected.")
        context.result.skipped += 1
        return None

    addon_temp = get_addon_temp_root(paths.temp_root, folder_name)
    if config.force_rebuild:
        for child in ("staging", "binarized", "textures", "configs"):
            selected_temp = os.path.join(addon_temp, child)
            if os.path.isdir(selected_temp):
                shutil.rmtree(selected_temp)

    folder_has_p3d = config.use_binarize and has_p3d_files(folder_path, context.exclude_patterns)
    staging = os.path.join(addon_temp, "staging") if config.convert_config or config.use_binarize else ""
    if staging:
        log("Copying source to staging folder...")
        copy_source_to_staging(
            folder_path,
            staging,
            context.exclude_patterns,
            log,
            True,
        )
    pack_source = staging or folder_path
    binarized = os.path.join(addon_temp, "binarized") if folder_has_p3d else ""
    work_dir = create_output_work_dir(output_pbo, folder_name)
    return BuildJob(
        folder_name=folder_name,
        folder_path=folder_path,
        output_pbo=output_pbo,
        output_kind="server" if server_only else "client",
        output_keys_dir=keys_dir,
        sign_output=sign_output,
        temp_output_pbo=os.path.join(work_dir, os.path.basename(output_pbo)),
        output_work_dir=work_dir,
        prefix=prefix,
        pack_source=pack_source,
        folder_has_p3d=folder_has_p3d,
        staging_dir=staging,
        binarized_dir=binarized,
        binarize_source=staging if folder_has_p3d and staging else folder_path,
        state_hash=state_hash,
    )


def _stage_job(context: _BuildContext, job: BuildJob, log: LogCallback) -> None:
    config = context.config
    if config.use_binarize and job.folder_has_p3d:
        pending = collect_non_binarized_p3ds(job.staging_dir, context.exclude_patterns)
        if pending:
            source, skipped = create_binarize_source_without_odol(
                job.binarize_source,
                context.paths.temp_root,
                job.folder_name,
                log,
                context.exclude_patterns,
            )
            if skipped:
                log(f"Binarize skips {skipped} already-ODOL P3D file(s).")
            run_dayz_binarize(
                source_dir=source,
                binarized_output_dir=job.binarized_dir,
                binarize_exe=config.binarize_exe,
                project_root=config.project_root,
                temp_dir=context.paths.temp_root,
                max_processes=config.max_processes,
                exclude_file=context.exclude_file,
                log=log,
                addon_name=job.folder_name,
            )
            overlay_tree(job.binarized_dir, job.staging_dir)
            context.result.p3d_recovered += ensure_p3d_files_in_staging(
                job.folder_path,
                job.staging_dir,
                log,
                context.exclude_patterns,
            )
            ensure_all_p3ds_binarized_in_staging(
                staging_dir=job.staging_dir,
                binarize_exe=config.binarize_exe,
                project_root=config.project_root,
                temp_dir=context.paths.temp_root,
                max_processes=config.max_processes,
                exclude_file=context.exclude_file,
                log=log,
                addon_name=job.folder_name,
                extra_patterns=context.exclude_patterns,
            )
        if config.protect_p3d:
            run_p3d_obfuscator_for_staging(
                job.staging_dir,
                config.p3d_obfuscator_exe,
                log,
                context.exclude_patterns,
            )

    if config.convert_config:
        ensure_config_cpp_files_in_staging(job.folder_path, job.pack_source, log, context.exclude_patterns)
        run_cfgconvert_rvmats_to_bin(job.pack_source, config.cfgconvert_exe, log, context.exclude_patterns)
        run_cfgconvert_to_bin(job.pack_source, config.cfgconvert_exe, log, context.exclude_patterns)
    if config.use_binarize:
        run_dayz_texheaders(
            source_dir=job.pack_source,
            binarize_exe=config.binarize_exe,
            project_root=config.project_root,
            temp_dir=context.paths.temp_root,
            max_processes=config.max_processes,
            exclude_file=context.exclude_file,
            log=log,
            addon_name=job.folder_name,
        )


def _pack_job(context: _BuildContext, job: BuildJob, log: LogCallback) -> None:
    config = context.config
    pack_pbo(
        job.pack_source,
        job.temp_output_pbo,
        job.prefix,
        log,
        context.exclude_patterns,
        exclude_pack_only=config.use_binarize,
    )
    verify_packed_pbo(
        job.temp_output_pbo,
        job.prefix,
        log,
        config.external_validator_exe,
    )
    if job.sign_output:
        wait_for_file_ready(job.temp_output_pbo, log)
        run_dssignfile(
            config.dssignfile_exe,
            config.private_key,
            job.temp_output_pbo,
            log,
        )
        context.result.signed += 1


def _publish_job(context: _BuildContext, job: BuildJob, log: LogCallback) -> None:
    replace_output_artifacts(
        job.temp_output_pbo,
        job.output_pbo,
        job.sign_output,
        log,
    )
    verify_published_output(job.output_pbo, job.sign_output, log)
    context.result.built += 1
    if job.sign_output and copy_bikey_to_keys(context.config.private_key, job.output_keys_dir, log):
        context.result.keys_copied += 1
    context.source_cache[job.folder_name] = {
        "hash": job.state_hash,
        "pbo": job.output_pbo,
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    save_build_cache(context.cache)


def _build_job(context: _BuildContext, job: BuildJob, log: LogCallback) -> None:
    log("")
    log(f"Packing addon: {job.folder_name} ({job.output_kind})")
    try:
        _stage_job(context, job, log)
        _pack_job(context, job, log)
        _publish_job(context, job, log)
    except Exception:
        context.result.failed += 1
        raise
    finally:
        cleanup_output_work_dir(job.output_work_dir, log)


def _log_summary(result: BuildResult, log: LogCallback) -> None:
    log("")
    log("=" * 80)
    log("Build summary")
    log(f"Targets:       {result.targets}")
    log(f"Built:         {result.built}")
    log(f"Skipped:       {result.skipped}")
    log(f"Signed:        {result.signed}")
    log(f"Keys copied:   {result.keys_copied}")
    log(f"P3D recovered: {result.p3d_recovered}")
    log(f"Failed:        {result.failed}")
    log(f"Time:          {format_duration(result.elapsed)}")
    if result.log_file:
        log(f"Log:           {result.log_file}")
    log("=" * 80)
    log("Build finished.")


def build_all(
    settings: BuildConfig | Mapping[str, Any],
    log: LogCallback,
    progress_callback: ProgressCallback,
) -> BuildResult:
    """Подготавливает, собирает, проверяет и атомарно публикует выбранные PBO."""
    started = time.time()
    config = settings if isinstance(settings, BuildConfig) else BuildConfig.from_mapping(settings)
    context = _prepare_build(config, log, progress_callback)
    jobs = [
        job
        for index, target in enumerate(context.targets, start=1)
        if (job := _prepare_job(context, target, index, log, progress_callback)) is not None
    ]
    for index, job in enumerate(jobs, start=1):
        progress_callback(index - 1, len(jobs))
        _build_job(context, job, log)
    progress_callback(len(context.targets), len(context.targets))
    save_build_cache(context.cache)
    context.result.elapsed = time.time() - started
    _log_summary(context.result, log)
    return context.result
