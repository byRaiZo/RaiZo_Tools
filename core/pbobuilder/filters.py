import fnmatch
import os

from .constants import (
    EXCLUDE_DIRS,
    EXCLUDE_EXTENSIONS,
    EXCLUDE_FILES,
    PACK_ONLY_EXCLUDE_EXTENSIONS,
    PACK_ONLY_EXCLUDE_FILES,
    REQUIRED_RVMAT_SUFFIXES,
)
from .errors import BuildError


def safe_ascii(value, label):
    try:
        return value.encode("ascii")
    except UnicodeEncodeError:
        raise BuildError(f"{label} contains non-ASCII characters: {value}")


def matches_exclude_pattern(name, patterns):
    if not patterns:
        return False
    value = name.lower()
    for pattern in patterns:
        test = pattern.strip().lower()
        if not test:
            continue
        if value == test:
            return True
        if fnmatch.fnmatch(value, test):
            return True
    return False


def should_skip_dir(dirname, extra_patterns=None):
    name = dirname.lower()
    if name in EXCLUDE_DIRS:
        return True
    if matches_exclude_pattern(name, extra_patterns):
        return True
    return False


def should_skip_file(filename, extra_patterns=None):
    name = filename.lower()
    # Never exclude config files by pattern. config.cpp must be converted; config.bin must be packed.
    if name in {"config.cpp", "config.bin"}:
        return False
    # P3D files are the core build target. If Binarize is enabled, every P3D must be processed and verified.
    if name.endswith(".p3d"):
        return False
    # Damage/destruct materials may only be referenced from config.cpp, not from P3D.
    # Keep them even when broad exclude patterns such as "*.rvmat" are configured.
    if name.endswith(REQUIRED_RVMAT_SUFFIXES):
        return False
    if name in EXCLUDE_FILES:
        return True
    if os.path.splitext(name)[1].lower() in EXCLUDE_EXTENSIONS:
        return True
    if matches_exclude_pattern(name, extra_patterns):
        return True
    return False


def should_skip_pack_file(filename, extra_patterns=None, exclude_pack_only=True):
    name = filename.lower()
    if exclude_pack_only:
        if name in PACK_ONLY_EXCLUDE_FILES:
            return True
        if os.path.splitext(name)[1].lower() in PACK_ONLY_EXCLUDE_EXTENSIONS:
            return True
    return should_skip_file(filename, extra_patterns)


def parse_exclude_patterns(raw_patterns):
    if not raw_patterns:
        return []
    normalized = raw_patterns.replace(";", ",")
    normalized = normalized.replace(chr(13), "")
    normalized = normalized.replace(chr(10), ",")
    result = []
    for item in normalized.split(","):
        pattern = item.strip()
        if pattern:
            result.append(pattern)
    return result


def create_temp_exclude_file(temp_root, raw_patterns, log):
    # Do not generate an exclude.lst file. Exclude patterns are used internally by the Python builder only.
    patterns = parse_exclude_patterns(raw_patterns)
    if patterns:
        log("Using exclude patterns internally only. No generated exclude.lst will be created.")
    return ""


def has_p3d_files(source_dir, extra_patterns=None):
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]

        for file in files:
            if should_skip_file(file, extra_patterns):
                continue

            if file.lower().endswith(".p3d"):
                return True

    return False


def has_paa_files(source_dir, extra_patterns=None):
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]

        for file in files:
            if should_skip_file(file, extra_patterns):
                continue

            if file.lower().endswith(".paa"):
                return True

    return False


def get_p3d_magic(file_path):
    try:
        with open(file_path, "rb") as file:
            return file.read(4)
    except OSError:
        return b""


def is_binarized_p3d(file_path):
    return get_p3d_magic(file_path) == b"ODOL"


def is_source_mlod_p3d(file_path):
    return get_p3d_magic(file_path) == b"MLOD"


def source_file_should_be_staged(filename, extra_patterns=None):
    # config.cpp must always be copied so CfgConvert can turn it into config.bin.
    if filename.lower() == "config.cpp":
        return True

    return not should_skip_file(filename, extra_patterns)
