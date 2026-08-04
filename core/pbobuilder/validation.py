from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .errors import BuildError
from .models import LogCallback
from .system import get_hidden_startupinfo, get_subprocess_creationflags

_ENTRY = struct.Struct("<IIIII")
_VERS = 0x56657273
_FOOTER_SIZE = 21
_MAX_TEXT = 4096


@dataclass(frozen=True, slots=True)
class PboEntry:
    name: str
    packing_method: int
    original_size: int
    reserved: int
    timestamp: int
    data_size: int
    data_offset: int


@dataclass(frozen=True, slots=True)
class PboValidation:
    prefix: str
    properties: dict[str, str]
    entries: tuple[PboEntry, ...]
    sha1: str
    size: int


def _read_cstring(handle, *, label: str) -> bytes:
    value = bytearray()
    while len(value) <= _MAX_TEXT:
        char = handle.read(1)
        if not char:
            raise BuildError(f"PBO validation failed: truncated {label}.")
        if char == b"\0":
            return bytes(value)
        value.extend(char)
    raise BuildError(f"PBO validation failed: {label} exceeds {_MAX_TEXT} bytes.")


def _decode_ascii(value: bytes, label: str) -> str:
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BuildError(f"PBO validation failed: {label} is not ASCII.") from exc


def _validate_entry_name(name: str) -> str:
    if not name or "/" in name or name.startswith("\\") or ":" in name:
        raise BuildError(f"PBO validation failed: invalid entry path '{name}'.")
    parts = PureWindowsPath(name).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise BuildError(f"PBO validation failed: unsafe entry path '{name}'.")
    return name.casefold()


def _sha1_before_footer(path: Path, length: int) -> bytes:
    digest = hashlib.sha1()
    remaining = length
    with path.open("rb") as handle:
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise BuildError("PBO validation failed: truncated body.")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.digest()


def validate_pbo(path: str | os.PathLike[str], expected_prefix: str = "") -> PboValidation:
    """Независимо разбирает PBO и проверяет структуру, размеры и SHA1-хвост."""
    pbo = Path(path)
    try:
        size = pbo.stat().st_size
    except OSError as exc:
        raise BuildError(f"PBO validation failed: cannot stat '{pbo}': {exc}") from exc
    if size < 1 + _ENTRY.size * 2 + _FOOTER_SIZE:
        raise BuildError("PBO validation failed: file is too small.")

    properties: dict[str, str] = {}
    raw_entries: list[tuple[str, tuple[int, int, int, int, int]]] = []
    with pbo.open("rb") as handle:
        if _read_cstring(handle, label="extension entry name") != b"":
            raise BuildError("PBO validation failed: missing extension header.")
        extension = _ENTRY.unpack(handle.read(_ENTRY.size))
        if extension != (_VERS, 0, 0, 0, 0):
            raise BuildError("PBO validation failed: invalid Vers extension header.")

        while True:
            key_raw = _read_cstring(handle, label="property key")
            if not key_raw:
                break
            value_raw = _read_cstring(handle, label="property value")
            key = _decode_ascii(key_raw, "property key")
            if key.casefold() in {item.casefold() for item in properties}:
                raise BuildError(f"PBO validation failed: duplicate property '{key}'.")
            properties[key] = _decode_ascii(value_raw, f"property '{key}'")

        seen: set[str] = set()
        while True:
            name_raw = _read_cstring(handle, label="entry name")
            fields_raw = handle.read(_ENTRY.size)
            if len(fields_raw) != _ENTRY.size:
                raise BuildError("PBO validation failed: truncated entry header.")
            fields = _ENTRY.unpack(fields_raw)
            if not name_raw:
                if fields != (0, 0, 0, 0, 0):
                    raise BuildError("PBO validation failed: invalid end-of-header entry.")
                break
            name = _decode_ascii(name_raw, "entry name")
            key = _validate_entry_name(name)
            if key in seen:
                raise BuildError(f"PBO validation failed: duplicate entry '{name}'.")
            seen.add(key)
            raw_entries.append((name, fields))

        data_start = handle.tell()

    data_size = sum(fields[4] for _, fields in raw_entries)
    footer_start = data_start + data_size
    if footer_start + _FOOTER_SIZE != size:
        raise BuildError(
            f"PBO validation failed: entry sizes do not match archive length ({footer_start + _FOOTER_SIZE} != {size})."
        )
    with pbo.open("rb") as handle:
        handle.seek(footer_start)
        if handle.read(1) != b"\0":
            raise BuildError("PBO validation failed: missing SHA1 footer marker.")
        stored_sha1 = handle.read(20)
    actual_sha1 = _sha1_before_footer(pbo, footer_start)
    if stored_sha1 != actual_sha1:
        raise BuildError("PBO validation failed: SHA1 footer mismatch.")

    offset = data_start
    entries: list[PboEntry] = []
    for name, fields in raw_entries:
        entries.append(PboEntry(name, *fields, data_offset=offset))
        offset += fields[4]

    prefix = next((value for key, value in properties.items() if key.casefold() == "prefix"), "")
    if expected_prefix and prefix != expected_prefix:
        raise BuildError(f"PBO validation failed: prefix mismatch; expected '{expected_prefix}', got '{prefix}'.")
    return PboValidation(prefix, properties, tuple(entries), actual_sha1.hex(), size)


def find_bankrev(configured: str = "") -> str:
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("BankRev.exe") or shutil.which("BankRev") or ""


def validate_with_bankrev(
    pbo_path: str | os.PathLike[str], executable: str = "", log: LogCallback | None = None
) -> bool:
    """Опционально проверяет чтение архива официальным BankRev ``-l``."""
    bankrev = find_bankrev(executable)
    if not bankrev:
        return False
    result = subprocess.run(
        [bankrev, "-l", os.fspath(pbo_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        creationflags=get_subprocess_creationflags(),
        startupinfo=get_hidden_startupinfo(),
    )
    if result.returncode != 0:
        detail = result.stdout.strip()[-2000:]
        raise BuildError(f"BankRev validation failed ({result.returncode}): {detail}")
    if log:
        log(f"External BankRev validation OK: {pbo_path}")
    return True
