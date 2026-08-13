import hashlib
import json
import os

from .constants import WIN_SEP
from .filters import should_skip_dir, should_skip_file
from .files import collect_config_include_paths_for_source, file_fingerprint, file_sha1_cached_for_build


def get_safe_temp_name(name):
    safe = name.strip() if name else "addon"
    safe = safe.replace("/", "_").replace(WIN_SEP, "_").replace(":", "_")
    return safe or "addon"


def get_addon_temp_root(temp_root, addon_name):
    return os.path.join(temp_root, "addons", get_safe_temp_name(addon_name))


def get_pbo_base_name(folder_name, pbo_name, selected_count):
    clean_name = pbo_name.strip() if pbo_name else ""
    if clean_name and selected_count == 1:
        clean_name = clean_name.replace(".pbo", "")
        clean_name = clean_name.replace("/", "_").replace(WIN_SEP, "_")
        return clean_name
    return folder_name


def read_pbo_prefix_file(source_dir):
    if not source_dir or not os.path.isdir(source_dir):
        return ""

    prefix_names = {"$pboprefix$", "$prefix$", "$pboprefix$.txt", "$prefix$.txt"}

    try:
        entries = os.listdir(source_dir)
    except OSError:
        return ""

    for entry in entries:
        if entry.lower() not in prefix_names:
            continue

        prefix_path = os.path.join(source_dir, entry)
        if not os.path.isfile(prefix_path):
            continue

        try:
            with open(prefix_path, "r", encoding="utf-8-sig", errors="ignore") as file:
                for line in file:
                    prefix = line.strip().strip('"').strip("'")
                    if prefix:
                        return prefix.replace("/", WIN_SEP).strip(WIN_SEP + "/")
        except OSError:
            return ""

    return ""


def get_pbo_prefix(pbo_base_name, source_dir=None):
    file_prefix = read_pbo_prefix_file(source_dir) if source_dir else ""

    if file_prefix:
        return file_prefix

    return pbo_base_name


def get_single_addon_target(source_root):
    normalized_root = os.path.normpath(source_root)
    folder_name = os.path.basename(normalized_root)
    if not folder_name:
        folder_name = "addon"
    return [(folder_name, normalized_root)]


def collect_subfolders(source_root, output_addons_dir):
    source_root = os.path.normpath(source_root)
    output_addons_dir = os.path.normpath(output_addons_dir)
    result = []
    for name in os.listdir(source_root):
        full = os.path.join(source_root, name)
        if not os.path.isdir(full):
            continue
        if should_skip_dir(name):
            continue
        if name.lower() in {"output", "addons", "keys"}:
            continue
        try:
            full_abs = os.path.abspath(full)
            output_abs = os.path.abspath(output_addons_dir)
            if full_abs == output_abs or output_abs.startswith(full_abs + os.sep):
                continue
        except Exception:
            pass
        result.append((name, full))
    result.sort(key=lambda x: x[0].lower())
    return result


def collect_config_subfolders(source_root, output_addons_dir):
    source_root = os.path.normpath(source_root)
    output_addons_dir = os.path.normpath(output_addons_dir) if output_addons_dir else ""
    result = []

    for name in os.listdir(source_root):
        full = os.path.join(source_root, name)
        if not os.path.isdir(full):
            continue
        if should_skip_dir(name):
            continue
        if name.lower() in {"output", "addons", "keys"}:
            continue
        try:
            full_abs = os.path.abspath(full)
            output_abs = os.path.abspath(output_addons_dir)
            if output_addons_dir and (full_abs == output_abs or output_abs.startswith(full_abs + os.sep)):
                continue
        except Exception:
            pass
        if not os.path.isfile(os.path.join(full, "config.cpp")):
            continue
        result.append((name, full))

    result.sort(key=lambda item: item[0].lower())
    return result


def detect_addon_targets(source_root, output_addons_dir):
    if not os.path.isdir(source_root):
        return []
    root_config_cpp = os.path.isfile(os.path.join(source_root, "config.cpp"))
    if root_config_cpp:
        return get_single_addon_target(source_root)
    config_targets = collect_config_subfolders(source_root, output_addons_dir)
    if config_targets:
        return config_targets
    return []


def compute_addon_state_hash(source_dir, prefix, settings, extra_patterns=None, build_hash_cache=None):
    digest = hashlib.sha1()
    content_safe_cache = True
    tracked_settings = {
        "prefix": prefix,
        "pbo_name": settings.get("pbo_name", ""),
        "use_binarize": bool(settings["use_binarize"]),
        "protect_p3d": bool(settings.get("protect_p3d", False)),
        "convert_config": bool(settings["convert_config"]),
        "sign_pbos": bool(settings["sign_pbos"]),
        "project_root": settings["project_root"],
        "output_root_dir": settings.get("output_root_dir", ""),
        "output_server_root_dir": settings.get("output_server_root_dir", ""),
        "exclude_patterns": settings["exclude_patterns"],
        "max_processes": settings["max_processes"],
        "content_safe_cache": content_safe_cache,
        "pbo_pack_style": "addonbuilder_compatible_v1",
        "rvmat_rapify": True,
        "reject_source_mlod_fallback": True,
        "verify_every_p3d_is_odol": True,
        "generate_texheaders": True,
        "config_include_expansion": True,
        "p3d_obfuscator_exe": file_fingerprint(
            settings.get("p3d_obfuscator_exe", ""), content_safe_cache, build_hash_cache
        ),
        "binarize_exe": file_fingerprint(settings.get("binarize_exe", ""), content_safe_cache, build_hash_cache),
        "cfgconvert_exe": file_fingerprint(settings.get("cfgconvert_exe", ""), content_safe_cache, build_hash_cache),
        "dssignfile_exe": file_fingerprint(settings.get("dssignfile_exe", ""), content_safe_cache, build_hash_cache),
    }
    private_key = settings.get("private_key", "")
    if settings.get("sign_pbos") and os.path.isfile(private_key):
        try:
            tracked_settings["private_key_name"] = os.path.basename(private_key)
            tracked_settings["private_key_size"] = os.path.getsize(private_key)
            tracked_settings["private_key_mtime_ns"] = os.stat(private_key).st_mtime_ns
            if content_safe_cache:
                tracked_settings["private_key_sha1"] = file_sha1_cached_for_build(private_key, build_hash_cache)
        except OSError:
            pass
    digest.update(json.dumps(tracked_settings, sort_keys=True).encode("utf-8"))
    for root, dirs, filenames in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for fname in sorted(filenames, key=lambda value: value.lower()):
            if should_skip_file(fname, extra_patterns):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, source_dir).replace(os.sep, WIN_SEP).lower()
            try:
                stat = os.stat(full)
            except OSError:
                continue
            digest.update(rel.encode("utf-8"))
            digest.update(str(stat.st_size).encode("ascii"))
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
            if content_safe_cache:
                digest.update(file_sha1_cached_for_build(full, build_hash_cache).encode("ascii"))

    for include_path in sorted(collect_config_include_paths_for_source(source_dir, extra_patterns), key=str.lower):
        rel = os.path.relpath(include_path, source_dir).replace(os.sep, WIN_SEP).lower()
        try:
            stat = os.stat(include_path)
        except OSError:
            continue
        digest.update(b"config_include:")
        digest.update(rel.encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        if content_safe_cache:
            digest.update(file_sha1_cached_for_build(include_path, build_hash_cache).encode("ascii"))
    return digest.hexdigest()


def format_duration(seconds):
    seconds = int(seconds)
    minutes = seconds // 60
    remaining = seconds % 60
    return f"{minutes:02d}:{remaining:02d}"
