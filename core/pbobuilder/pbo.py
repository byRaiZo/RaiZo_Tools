import glob
import hashlib
import os
import shutil
import struct
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .constants import COPY_CHUNK_SIZE, WIN_SEP, ZERO
from .errors import BuildError
from .filters import safe_ascii, should_skip_dir, should_skip_pack_file
from .system import get_app_data_dir, get_hidden_startupinfo, get_subprocess_creationflags
from .targets import get_safe_temp_name
from .validation import validate_pbo, validate_with_bankrev


def get_signature_pattern_for_pbo(pbo_path):
    return glob.escape(os.fspath(pbo_path)) + ".*.bisign"


def find_new_signature_for_pbo(pbo_path):
    signatures = glob.glob(get_signature_pattern_for_pbo(pbo_path))
    if not signatures:
        return ""
    signatures.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return signatures[0]


def remove_old_signatures(pbo_path, log):
    old_signatures = glob.glob(get_signature_pattern_for_pbo(pbo_path))
    for signature in old_signatures:
        try:
            os.remove(signature)
            log(f"Removed old signature: {signature}")
        except Exception as e:
            raise BuildError(f"Could not remove old signature: {signature} ({e})")


def clean_output_for_pbo(pbo_path, log):
    if os.path.isfile(pbo_path):
        os.remove(pbo_path)
        log(f"Removed old PBO: {pbo_path}")
    remove_old_signatures(pbo_path, log)


def wait_for_file_ready(file_path, log, timeout_seconds=10):
    start_time = time.time()
    last_size = -1
    stable_hits = 0
    log(f"Waiting for file to be ready: {file_path}")
    while time.time() - start_time < timeout_seconds:
        if os.path.isfile(file_path):
            try:
                current_size = os.path.getsize(file_path)
                if current_size > 0 and current_size == last_size:
                    stable_hits += 1
                else:
                    stable_hits = 0
                if stable_hits >= 2:
                    log(f"File ready: {file_path} ({current_size} bytes)")
                    return
                last_size = current_size
            except OSError:
                stable_hits = 0
        time.sleep(0.25)
    raise BuildError(f"File was not ready after {timeout_seconds} seconds: {file_path}")


def get_bikey_for_private_key(private_key):
    if not private_key:
        return ""
    key_path = Path(private_key)
    if key_path.suffix.lower() != ".biprivatekey":
        return ""
    bikey = key_path.with_suffix(".bikey")
    if bikey.is_file():
        return str(bikey)
    matches = list(key_path.parent.glob(key_path.stem + "*.bikey"))
    if matches:
        matches.sort(key=lambda path: path.name.lower())
        return str(matches[0])
    return ""


def copy_bikey_to_keys(private_key, output_keys_dir, log):
    bikey = get_bikey_for_private_key(private_key)
    if not bikey:
        log("WARNING: Matching .bikey was not found. Nothing copied to Keys folder.")
        return ""

    os.makedirs(output_keys_dir, exist_ok=True)
    target = os.path.join(output_keys_dir, os.path.basename(bikey))

    if os.path.isfile(target):
        log(f"Bikey already exists. Skipping copy: {target}")
        return ""

    shutil.copy2(bikey, target)
    log(f"Copied bikey -> {target}")
    return target


def run_dssignfile(dssignfile_exe, private_key, pbo_path, log):
    if not dssignfile_exe or not os.path.isfile(dssignfile_exe):
        raise BuildError("DSSignFile.exe not found. Select the DayZ Tools DSSignFile.exe path.")
    if not private_key or not os.path.isfile(private_key):
        raise BuildError("Private key not found. Select your .biprivatekey file.")
    if not private_key.lower().endswith(".biprivatekey"):
        raise BuildError("Selected private key does not end with .biprivatekey.")
    if not os.path.isfile(pbo_path):
        raise BuildError(f"PBO does not exist and cannot be signed: {pbo_path}")

    original_pbo_dir = os.path.dirname(os.path.abspath(pbo_path))
    pbo_name = os.path.basename(pbo_path)
    key_name = os.path.basename(private_key)
    signing_root = get_app_data_dir() / "signing_temp" / f"sign_{os.getpid()}_{time.time_ns()}"
    work_pbo = signing_root / pbo_name
    work_key = signing_root / key_name

    try:
        signing_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pbo_path, work_pbo)
        shutil.copy2(private_key, work_key)
        remove_old_signatures(str(work_pbo), log)

        cmd = [dssignfile_exe, key_name, pbo_name]

        log("")
        log("Signing PBO in isolated temp folder:")
        log(f"  PBO:         {pbo_name}")
        log(f"  Key:         {key_name}")
        log(f"  Work folder: {signing_root}")
        log(f"  Tool:        {dssignfile_exe}")
        log("")

        result = subprocess.run(
            cmd,
            cwd=str(signing_root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=get_subprocess_creationflags(),
            startupinfo=get_hidden_startupinfo(),
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                log(line)
        else:
            log("DSSignFile returned no output.")

        work_signatures = glob.glob(get_signature_pattern_for_pbo(str(work_pbo)))
        work_signatures.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        if result.returncode != 0:
            raise BuildError(f"DSSignFile failed with exit code {result.returncode}: {pbo_path}")
        if not work_signatures:
            raise BuildError(f"DSSignFile finished but no .bisign was created for: {pbo_path}")

        for work_signature in work_signatures:
            final_signature = os.path.join(original_pbo_dir, os.path.basename(work_signature))
            shutil.copy2(work_signature, final_signature)
            if not os.path.isfile(final_signature):
                raise BuildError(f"Could not copy signature back to output folder: {final_signature}")
            log(f"Created signature: {final_signature}")

    finally:
        # The private key is copied into signing_root because DSSignFile is most reliable
        # when the key and PBO are in the same working folder. Always remove that copy.
        try:
            shutil.rmtree(signing_root, ignore_errors=True)
        except Exception as e:
            log(f"WARNING: Could not clean signing temp folder: {signing_root} ({e})")


def create_output_work_dir(output_pbo, addon_name):
    output_dir = os.path.dirname(os.path.abspath(output_pbo))
    work_root = os.path.join(output_dir, "_pbo_builder_tmp")
    work_dir = os.path.join(work_root, f"{get_safe_temp_name(addon_name)}_{os.getpid()}_{time.time_ns()}")
    os.makedirs(work_dir, exist_ok=True)
    return work_dir


def create_publish_backup_dir(final_pbo):
    final_dir = os.path.dirname(os.path.abspath(final_pbo))
    backup_root = os.path.join(final_dir, "_pbo_builder_backup")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = os.path.splitext(os.path.basename(final_pbo))[0]
    backup_dir = os.path.join(backup_root, f"{name}_{stamp}_{os.getpid()}_{time.time_ns()}")
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def copy_existing_output_artifacts_to_backup(final_pbo, backup_dir, log):
    backed_up = []

    if os.path.isfile(final_pbo):
        backup_pbo = os.path.join(backup_dir, os.path.basename(final_pbo))
        shutil.copy2(final_pbo, backup_pbo)
        backed_up.append(backup_pbo)
        log(f"Backed up existing PBO: {backup_pbo}")

    for signature in glob.glob(get_signature_pattern_for_pbo(final_pbo)):
        backup_signature = os.path.join(backup_dir, os.path.basename(signature))
        shutil.copy2(signature, backup_signature)
        backed_up.append(backup_signature)
        log(f"Backed up existing signature: {backup_signature}")

    return backed_up


def remove_current_output_artifacts(final_pbo, log):
    if os.path.isfile(final_pbo):
        os.remove(final_pbo)
        log(f"Removed partially published PBO: {final_pbo}")

    for signature in glob.glob(get_signature_pattern_for_pbo(final_pbo)):
        try:
            os.remove(signature)
            log(f"Removed partially published signature: {signature}")
        except FileNotFoundError:
            pass


def restore_output_artifacts_from_backup(final_pbo, backup_dir, log):
    if not backup_dir or not os.path.isdir(backup_dir):
        return

    final_dir = os.path.dirname(os.path.abspath(final_pbo))

    log("Attempting to restore previous output artifacts from backup.")
    remove_current_output_artifacts(final_pbo, log)

    backup_pbo = os.path.join(backup_dir, os.path.basename(final_pbo))
    if os.path.isfile(backup_pbo):
        shutil.copy2(backup_pbo, final_pbo)
        log(f"Restored previous PBO: {final_pbo}")

    for backup_signature in glob.glob(
        get_signature_pattern_for_pbo(os.path.join(backup_dir, os.path.basename(final_pbo)))
    ):
        final_signature = os.path.join(final_dir, os.path.basename(backup_signature))
        shutil.copy2(backup_signature, final_signature)
        log(f"Restored previous signature: {final_signature}")


def safe_remove_empty_parent(path_value, stop_at):
    try:
        current = Path(path_value)
        stop = Path(stop_at).resolve(strict=False)

        while current.exists() and current.is_dir():
            if current.resolve(strict=False) == stop:
                break
            if any(current.iterdir()):
                break
            current.rmdir()
            current = current.parent
    except Exception:
        pass


def validate_publish_backup(final_pbo, backup_dir, existing_signatures):
    # Validate that the backup contains every existing published artifact
    # before we touch the published output set.
    if os.path.isfile(final_pbo):
        backup_pbo = os.path.join(backup_dir, os.path.basename(final_pbo))
        if not os.path.isfile(backup_pbo):
            raise BuildError(f"Backup validation failed. Missing backup PBO: {backup_pbo}")

    for signature in existing_signatures:
        backup_signature = os.path.join(backup_dir, os.path.basename(signature))
        if not os.path.isfile(backup_signature):
            raise BuildError(f"Backup validation failed. Missing backup signature: {backup_signature}")


def replace_output_artifacts(temp_pbo, final_pbo, sign_pbos, log):
    if not os.path.isfile(temp_pbo):
        raise BuildError(f"Temporary PBO does not exist and cannot replace output: {temp_pbo}")

    final_dir = os.path.dirname(os.path.abspath(final_pbo))
    os.makedirs(final_dir, exist_ok=True)

    temp_signatures = glob.glob(get_signature_pattern_for_pbo(temp_pbo))
    temp_signatures.sort(key=lambda path: os.path.basename(path).lower())

    if sign_pbos and not temp_signatures:
        raise BuildError(f"Signed build expected a .bisign but none was created for: {temp_pbo}")

    publish_id = f"{os.getpid()}_{time.time_ns()}"
    prepared_signature_paths = []
    backup_dir = create_publish_backup_dir(final_pbo)
    backup_root = os.path.dirname(backup_dir)
    publish_started = False

    try:
        log("Preparing output publish set.")
        existing_signatures = glob.glob(get_signature_pattern_for_pbo(final_pbo))
        existing_signatures.sort(key=lambda path: os.path.basename(path).lower())

        copy_existing_output_artifacts_to_backup(final_pbo, backup_dir, log)
        validate_publish_backup(final_pbo, backup_dir, existing_signatures)

        # Copy new signatures to final-folder temp names before touching the published PBO.
        # This catches permission, disk, and antivirus problems before the current PBO is replaced.
        for temp_signature in temp_signatures:
            final_signature = os.path.join(final_dir, os.path.basename(temp_signature))
            prepared_signature = final_signature + f".new_{publish_id}"
            shutil.copy2(temp_signature, prepared_signature)
            prepared_signature_paths.append((prepared_signature, final_signature))
            log(f"Prepared signature for publish: {prepared_signature}")

        log("Publishing output artifacts after successful build validation.")

        # From this point forward, published output may be modified and rollback may be needed.
        publish_started = True
        os.replace(temp_pbo, final_pbo)
        log(f"Output PBO updated: {final_pbo}")

        new_signature_names = {os.path.basename(final_signature) for _, final_signature in prepared_signature_paths}

        for prepared_signature, final_signature in prepared_signature_paths:
            os.replace(prepared_signature, final_signature)
            log(f"Output signature updated: {final_signature}")

        # Remove signatures that belonged to the previous PBO but are not part of the new publish set.
        for old_signature in glob.glob(get_signature_pattern_for_pbo(final_pbo)):
            if os.path.basename(old_signature) not in new_signature_names:
                os.remove(old_signature)
                log(f"Removed stale signature: {old_signature}")

        shutil.rmtree(backup_dir, ignore_errors=True)
        safe_remove_empty_parent(backup_root, final_dir)
        log("Output publish set completed successfully.")

    except Exception as e:
        log(f"ERROR: Output publish failed: {e}")

        for prepared_signature, _ in prepared_signature_paths:
            if os.path.isfile(prepared_signature):
                try:
                    os.remove(prepared_signature)
                    log(f"Removed prepared signature after failed publish: {prepared_signature}")
                except Exception as cleanup_error:
                    log(f"WARNING: Could not remove prepared signature: {prepared_signature} ({cleanup_error})")

        if publish_started:
            try:
                restore_output_artifacts_from_backup(final_pbo, backup_dir, log)
                log(f"Previous output restored from backup: {backup_dir}")
            except Exception as restore_error:
                log(f"ERROR: Could not restore previous output from backup: {backup_dir} ({restore_error})")
                log("Manual recovery may be required. Backup folder was kept.")
        else:
            log("Publish had not started yet. Existing output was left untouched.")
            shutil.rmtree(backup_dir, ignore_errors=True)
            safe_remove_empty_parent(backup_root, final_dir)

        raise BuildError(
            f"Output publish failed. Existing output was left untouched or restored if needed. Details: {e}"
        )


def cleanup_output_work_dir(work_dir, log=None):
    if not work_dir:
        return

    try:
        shutil.rmtree(work_dir, ignore_errors=True)
        parent = os.path.dirname(work_dir)
        if os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
    except Exception as e:
        if log:
            log(f"WARNING: Could not clean output work folder: {work_dir} ({e})")


def read_packed_pbo_prefix(pbo_path):
    try:
        with open(pbo_path, "rb") as file:
            data = file.read(65536)
    except OSError:
        return ""

    marker = b"prefix" + ZERO
    index = data.find(marker)
    if index < 0:
        return ""

    start = index + len(marker)
    end = data.find(ZERO, start)
    if end < 0:
        return ""

    return data[start:end].decode("ascii", errors="ignore")


def verify_packed_pbo(pbo_path, expected_prefix, log, external_validator_exe=""):
    report = validate_pbo(pbo_path, expected_prefix)
    log(
        "Post-pack verification OK: "
        f"size={report.size:,} bytes, files={len(report.entries)}, "
        f"prefix={report.prefix or '<none>'}, sha1={report.sha1}"
    )
    validate_with_bankrev(pbo_path, external_validator_exe, log)


def verify_published_output(pbo_path, sign_pbos, log):
    if not os.path.isfile(pbo_path):
        raise BuildError(f"Published output verification failed. PBO is missing: {pbo_path}")

    if sign_pbos and not find_new_signature_for_pbo(pbo_path):
        raise BuildError(f"Published output verification failed. Signature is missing for: {pbo_path}")

    log("Published output verification OK.")


def pack_pbo(source_dir, output_path, prefix, log, extra_patterns=None, exclude_pack_only=True):
    source_dir = os.path.normpath(source_dir)
    output_path = os.path.normpath(output_path)
    if not os.path.isdir(source_dir):
        raise BuildError(f"Source is not a directory: {source_dir}")
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    files = []
    for root, dirs, filenames in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for fname in filenames:
            if should_skip_pack_file(fname, extra_patterns, exclude_pack_only):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, source_dir).replace(os.sep, WIN_SEP)
            size = os.path.getsize(full)
            timestamp = max(0, int(os.path.getmtime(full)))
            files.append((rel, full, size, timestamp))
    files.sort(key=lambda x: x[0].lower())

    header = bytearray()
    header.extend(ZERO)
    header.extend(struct.pack("<I", 0x56657273))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))
    header.extend(b"product")
    header.extend(ZERO)
    header.extend(b"dayz ugc")
    header.extend(ZERO)
    if prefix:
        header.extend(b"prefix")
        header.extend(ZERO)
        header.extend(safe_ascii(prefix, "PBO prefix"))
        header.extend(ZERO)
    header.extend(ZERO)
    for rel, full, size, timestamp in files:
        header.extend(safe_ascii(rel, "File path"))
        header.extend(ZERO)
        header.extend(struct.pack("<I", 0))
        header.extend(struct.pack("<I", 0))
        header.extend(struct.pack("<I", 0))
        header.extend(struct.pack("<I", timestamp))
        header.extend(struct.pack("<I", size))
    header.extend(ZERO)
    header.extend(struct.pack("<IIIII", 0, 0, 0, 0, 0))

    temp_output_path = output_path + ".tmp"
    sha = hashlib.sha1()
    total_bytes = 0
    try:
        with open(temp_output_path, "wb") as out:
            out.write(header)
            sha.update(header)
            total_bytes += len(header)
            for rel, full, size, timestamp in files:
                with open(full, "rb") as f:
                    while True:
                        chunk = f.read(COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        out.write(chunk)
                        sha.update(chunk)
                        total_bytes += len(chunk)
            digest = sha.digest()
            out.write(ZERO)
            out.write(digest)
            total_bytes += 1 + len(digest)
        os.replace(temp_output_path, output_path)
    except Exception:
        if os.path.isfile(temp_output_path):
            try:
                os.remove(temp_output_path)
            except Exception:
                pass
        raise
    log(f"Packed {len(files):4d} files / {total_bytes:,} bytes -> {output_path}")
