import hashlib
import os
import shutil
from pathlib import Path

from .constants import BUILDER_TEMP_CHILDREN, COPY_CHUNK_SIZE, TEMP_MARKER_FILE, WIN_SEP
from .errors import BuildError
from .filters import (
    is_binarized_p3d,
    is_source_mlod_p3d,
    should_skip_dir,
    should_skip_file,
    source_file_should_be_staged,
)


def file_sha1(file_path):
    digest = hashlib.sha1()

    with open(file_path, "rb") as file:
        while True:
            chunk = file.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)

    return digest.hexdigest()


def file_sha1_cached_for_build(file_path, build_hash_cache=None):
    # Per-build cache only.
    # Do not persist source file hashes across runs; content-safe builds must still
    # detect same-size/same-mtime edits between separate builds.
    if build_hash_cache is None:
        return file_sha1(file_path)

    try:
        stat = os.stat(file_path)
    except OSError:
        return file_sha1(file_path)

    key = os.path.normcase(os.path.abspath(file_path))
    cached = build_hash_cache.get(key)

    if isinstance(cached, dict):
        if cached.get("size") == stat.st_size and cached.get("mtime_ns") == stat.st_mtime_ns and cached.get("sha1"):
            return cached["sha1"]

    digest = file_sha1(file_path)
    build_hash_cache[key] = {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha1": digest,
    }

    return digest


def files_have_same_content(source_file, target_file):
    try:
        with open(source_file, "rb") as src, open(target_file, "rb") as dst:
            while True:
                src_chunk = src.read(COPY_CHUNK_SIZE)
                dst_chunk = dst.read(COPY_CHUNK_SIZE)

                if src_chunk != dst_chunk:
                    return False

                if not src_chunk:
                    return True
    except OSError:
        return False


def file_fingerprint(file_path, include_content=False, build_hash_cache=None):
    if not file_path or not os.path.isfile(file_path):
        return {"path": file_path or "", "exists": False}

    try:
        stat = os.stat(file_path)
        info = {
            "path": os.path.abspath(file_path),
            "exists": True,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

        if include_content:
            info["sha1"] = file_sha1_cached_for_build(file_path, build_hash_cache)

        return info
    except OSError:
        return {"path": file_path or "", "exists": False}


def files_are_same_for_staging(source_file, target_file, content_safe=False):
    if not os.path.isfile(target_file):
        return False

    try:
        source_stat = os.stat(source_file)
        target_stat = os.stat(target_file)
    except OSError:
        return False

    # Size mismatch always means we need to update.
    if source_stat.st_size != target_stat.st_size:
        return False

    if content_safe:
        return files_have_same_content(source_file, target_file)

    # Fast mode: if source is newer, update staging.
    # If target is newer or same age and same size, keep it.
    if source_stat.st_mtime_ns > target_stat.st_mtime_ns:
        return False

    return True


def copy_source_to_staging(source_dir, staging_dir, extra_patterns=None, log=None, content_safe=False):
    source_dir = os.path.normpath(source_dir)
    staging_dir = os.path.normpath(staging_dir)

    os.makedirs(staging_dir, exist_ok=True)

    expected_rel_paths = set()
    copied = 0
    updated = 0
    unchanged = 0
    removed = 0

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]

        for file in files:
            if not source_file_should_be_staged(file, extra_patterns):
                continue

            source_file = os.path.join(root, file)
            rel_path = os.path.relpath(source_file, source_dir)
            rel_key = rel_path.replace(os.sep, WIN_SEP).lower()
            expected_rel_paths.add(rel_key)

            target_file = os.path.join(staging_dir, rel_path)

            if files_are_same_for_staging(source_file, target_file, content_safe):
                unchanged += 1
                continue

            os.makedirs(os.path.dirname(target_file), exist_ok=True)

            existed = os.path.isfile(target_file)
            shutil.copy2(source_file, target_file)

            if existed:
                updated += 1
            else:
                copied += 1

    # Remove files from staging that no longer exist in source or are now excluded.
    # This also removes stale generated config.bin files, which are recreated later by CfgConvert.
    for root, dirs, files in os.walk(staging_dir, topdown=False):
        for file in files:
            staged_file = os.path.join(root, file)
            rel_path = os.path.relpath(staged_file, staging_dir)
            rel_key = rel_path.replace(os.sep, WIN_SEP).lower()

            if rel_key not in expected_rel_paths:
                os.remove(staged_file)
                removed += 1

        # Clean up empty folders, but keep the staging root itself.
        if root != staging_dir:
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass

    if log:
        log(
            "Incremental staging: "
            f"copied={copied}, updated={updated}, unchanged={unchanged}, removed={removed}, content_safe={content_safe}"
        )


def ensure_p3d_files_in_staging(source_dir, staging_dir, log, extra_patterns=None):
    if not os.path.isdir(source_dir):
        log(f"WARNING: Source folder does not exist while ensuring P3Ds: {source_dir}")
        return 0

    if not os.path.isdir(staging_dir):
        os.makedirs(staging_dir, exist_ok=True)

    copied = 0
    already_present = 0
    skipped = 0

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]

        for file in files:
            if not file.lower().endswith(".p3d"):
                continue

            if should_skip_file(file, extra_patterns):
                skipped += 1
                continue

            source_p3d = os.path.join(root, file)
            rel_p3d = os.path.relpath(source_p3d, source_dir)
            target_p3d = os.path.join(staging_dir, rel_p3d)

            if os.path.isfile(target_p3d):
                already_present += 1
                continue

            rel_log = rel_p3d.replace(os.sep, WIN_SEP)
            if not is_binarized_p3d(source_p3d):
                if is_source_mlod_p3d(source_p3d):
                    raise BuildError(
                        "Binarize did not produce an output P3D and the source is still MLOD. "
                        f"Refusing to pack source model into release PBO: {rel_log}"
                    )
                raise BuildError(
                    "Binarize did not produce an output P3D and the source is not an ODOL model. "
                    f"Refusing to pack unverified model into release PBO: {rel_log}"
                )

            os.makedirs(os.path.dirname(target_p3d), exist_ok=True)
            shutil.copy2(source_p3d, target_p3d)
            copied += 1

            log(f"Copied already-binarized P3D missing from Binarize output: {rel_log}")

    if copied:
        log(f"Copied {copied} already-binarized P3D file(s) that Binarize did not output.")
    else:
        log(f"All non-excluded source P3D files are already present in staging ({already_present} checked).")

    if skipped:
        log(f"Skipped {skipped} excluded P3D file(s) during P3D fallback check.")

    return copied


def ensure_config_cpp_files_in_staging(source_dir, staging_dir, log, extra_patterns=None):
    if not os.path.isdir(source_dir):
        log(f"WARNING: Source folder does not exist while ensuring configs: {source_dir}")
        return 0

    if not os.path.isdir(staging_dir):
        os.makedirs(staging_dir, exist_ok=True)

    copied = 0
    skipped_dirs = 0

    for root, dirs, files in os.walk(source_dir):
        before_count = len(dirs)
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        skipped_dirs += before_count - len(dirs)

        for file in files:
            if file.lower() != "config.cpp":
                continue

            # config.cpp must always be preserved only inside included folders.
            # Excluded folders such as "source" must not be reintroduced here.
            source_config = os.path.join(root, file)
            rel_config = os.path.relpath(source_config, source_dir)
            target_config = os.path.join(staging_dir, rel_config)

            os.makedirs(os.path.dirname(target_config), exist_ok=True)
            shutil.copy2(source_config, target_config)
            copied += 1

            rel_log = rel_config.replace(os.sep, WIN_SEP)
            log(f"Ensured config.cpp in staging: {rel_log}")

    if copied:
        log(f"Ensured {copied} config.cpp file(s) are present in staging.")
    else:
        log("No included config.cpp files found while ensuring configs in staging.")

    if skipped_dirs:
        log(f"Skipped {skipped_dirs} excluded folder(s) while ensuring config.cpp files.")

    return copied


def overlay_tree(source_dir, destination_dir):
    if not os.path.isdir(source_dir):
        return
    for root, dirs, files in os.walk(source_dir):
        rel_root = os.path.relpath(root, source_dir)
        target_root = destination_dir if rel_root == "." else os.path.join(destination_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for file in files:
            source_file = os.path.join(root, file)
            target_file = os.path.join(target_root, file)
            shutil.copy2(source_file, target_file)


def resolve_for_safety(path_value):
    return Path(path_value).expanduser().resolve(strict=False)


def paths_overlap(path_a, path_b):
    if not path_a or not path_b:
        return False

    try:
        a = resolve_for_safety(path_a)
        b = resolve_for_safety(path_b)
    except Exception:
        return False

    try:
        if a == b:
            return True
        a.relative_to(b)
        return True
    except ValueError:
        pass

    try:
        b.relative_to(a)
        return True
    except ValueError:
        return False


def get_dangerous_temp_root_reason(temp_root, source_root="", output_root=""):
    if not temp_root:
        return "Temp dir is empty."

    try:
        root_path = resolve_for_safety(temp_root)
    except Exception as e:
        return f"Could not resolve temp dir: {e}"

    root_text = str(root_path)

    if len(root_text) < 5:
        return f"Temp dir path is too short: {root_text}"

    if root_path.parent == root_path:
        return f"Temp dir points to a filesystem root: {root_text}"

    # Reject plain drive roots such as C:\ or P:\.
    drive, tail = os.path.splitdrive(root_text)
    if drive and tail in {"\\", "/"}:
        return f"Temp dir points to a drive root: {root_text}"

    important_paths = [
        Path.home(),
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
    ]

    for env_name in ["ProgramFiles", "ProgramFiles(x86)", "SystemRoot", "WINDIR", "LOCALAPPDATA", "APPDATA"]:
        env_value = os.environ.get(env_name)
        if env_value:
            important_paths.append(Path(env_value))

    for important_path in important_paths:
        try:
            if root_path == resolve_for_safety(important_path):
                return f"Temp dir points to an important folder: {root_text}"
        except Exception:
            pass

    lower_parts = {part.lower() for part in root_path.parts}
    risky_folder_names = {
        "steam",
        "steamapps",
        "common",
        "dayz tools",
        "dayz",
        "program files",
        "program files (x86)",
        "windows",
    }

    if lower_parts.intersection(risky_folder_names):
        return f"Temp dir appears to be inside an important game/system folder: {root_text}"

    if source_root and paths_overlap(root_path, source_root):
        return "Temp dir overlaps with the selected Source root."

    if output_root and paths_overlap(root_path, output_root):
        return "Temp dir overlaps with the selected Output root."

    return ""


def ensure_builder_temp_root(temp_root, log=None, source_root="", output_root=""):
    reason = get_dangerous_temp_root_reason(temp_root, source_root, output_root)
    if reason:
        raise BuildError(f"Unsafe temp dir. {reason}")

    root_path = resolve_for_safety(temp_root)
    root_path.mkdir(parents=True, exist_ok=True)

    marker_path = root_path / TEMP_MARKER_FILE
    if not marker_path.exists():
        marker_path.write_text(
            "PBO Builder(byRaiZo) temp folder marker.\n"
            "This file allows the builder to safely clean only known builder temp folders.\n",
            encoding="utf-8",
        )
        if log:
            log(f"Created temp marker: {marker_path}")

    return root_path


def clear_temp_folder(temp_root, log, source_root="", output_root=""):
    root_path = ensure_builder_temp_root(temp_root, None, source_root, output_root)
    marker_path = root_path / TEMP_MARKER_FILE

    if not marker_path.is_file():
        raise BuildError("Temp marker file is missing. Refusing cleanup for safety: " + str(marker_path))

    log(f"Safe temp cleanup: {root_path}")
    log("Only known PBO Builder(byRaiZo) temp folders will be removed.")

    removed = 0

    for child_name in sorted(BUILDER_TEMP_CHILDREN):
        child_path = root_path / child_name

        if not child_path.exists():
            continue

        resolved_child = resolve_for_safety(child_path)

        try:
            resolved_child.relative_to(root_path)
        except ValueError:
            raise BuildError(f"Refusing to delete path outside temp root: {resolved_child}")

        if resolved_child == root_path:
            raise BuildError(f"Refusing to delete temp root itself: {resolved_child}")

        if child_path.is_dir():
            shutil.rmtree(child_path)
            removed += 1
            log(f"Removed temp folder: {child_path}")
        else:
            child_path.unlink()
            removed += 1
            log(f"Removed temp file: {child_path}")

    if removed == 0:
        log("No known builder temp folders found to remove.")

    log("Safe temp cleanup finished.")


def clear_full_temp_folder(temp_root, log, source_root="", output_root=""):
    root_path = ensure_builder_temp_root(temp_root, None, source_root, output_root)
    marker_path = root_path / TEMP_MARKER_FILE

    if not marker_path.is_file():
        raise BuildError("Temp marker file is missing. Refusing full cleanup for safety: " + str(marker_path))

    log(f"Full temp cleanup: {root_path}")
    log("All files and folders inside the temp root will be removed, except the builder marker file.")

    removed = 0

    for item in root_path.iterdir():
        if item.name == TEMP_MARKER_FILE:
            continue

        resolved_item = resolve_for_safety(item)

        try:
            resolved_item.relative_to(root_path)
        except ValueError:
            raise BuildError(f"Refusing to delete path outside temp root: {resolved_item}")

        if resolved_item == root_path:
            raise BuildError(f"Refusing to delete temp root itself: {resolved_item}")

        if item.is_dir():
            shutil.rmtree(item)
            removed += 1
            log(f"Removed temp folder: {item}")
        else:
            item.unlink()
            removed += 1
            log(f"Removed temp file: {item}")

    if removed == 0:
        log("Full temp cleanup found nothing to remove.")

    log("Full temp cleanup finished.")
