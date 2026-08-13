from pathlib import Path


APP_TITLE = "PBO Builder(byRaiZo)"
APP_VERSION = "1.0.6"
APP_AUTHOR = "RaiZo"
APP_LICENSE_NAME = "GPLv3 (embedded in RaiZo Tools)"
APP_LICENSE_TEXT = """PBO Builder(byRaiZo) embedded component

Copyright (c) 2026 RaiZo

This embedded copy is distributed as part of RaiZo Tools under GPLv3 with
permission from its copyright holder. Standalone releases keep their own
license.

This software is provided "as is", without warranty of any kind, express or implied.

The author is not responsible for damaged files, lost data, invalid PBOs, failed
builds, server issues, broken signatures, leaked keys, or any other damage caused
by the use or misuse of this software.

Important:
Never share your .biprivatekey.
Only distribute the matching .bikey.
"""
APP_ICON_FILE = "assets/icon.ico"

EXCLUDE_DIRS = {".git", ".svn", ".vscode", ".idea", "__pycache__"}
EXCLUDE_FILES = {
    ".gitignore",
    ".gitattributes",
    "thumbs.db",
    "desktop.ini",
    ".ds_store",
    "$prefix$",
    "$pboprefix$",
    "$prefix$.txt",
    "$pboprefix$.txt",
}
EXCLUDE_EXTENSIONS = {".delete"}
PACK_ONLY_EXCLUDE_FILES = set()
PACK_ONLY_EXCLUDE_EXTENSIONS = {".cfg"}
REQUIRED_RVMAT_SUFFIXES = ("_damage.rvmat", "_destruct.rvmat")

DEFAULT_TEMP_DIR = str(Path("P:/Temp"))
DEFAULT_PROJECT_ROOT = "P:"
DEFAULT_EXCLUDE_PATTERNS = (
    "*.h,*.hpp,*.png,*.cpp,*.txt,thumbs.db,*.dep,*.bak,*.log,*.pew,source,*.tga,*.bat,*.psd,*.cmd,*.mcr,*.fbx,*.max"
)


GRAPHITE_BG = "#24262b"
GRAPHITE_HEADER = "#1f2126"
GRAPHITE_CARD = "#2f3238"
GRAPHITE_CARD_SOFT = "#383c44"
GRAPHITE_FIELD = "#292c32"
GRAPHITE_BORDER = "#4a505b"
GRAPHITE_BORDER_SOFT = "#3a3f48"
GRAPHITE_TEXT = "#f1f1f1"
GRAPHITE_MUTED = "#b8bec8"
GRAPHITE_ACCENT = "#a74747"
GRAPHITE_ACCENT_DARK = "#7f3434"
GRAPHITE_ACCENT_HOVER = "#b65353"
GRAPHITE_PREFLIGHT = "#4f5f72"
GRAPHITE_PREFLIGHT_ACTIVE = "#60748b"
GRAPHITE_PREFLIGHT_HOVER = "#6e849d"
GRAPHITE_WARNING = "#d6aa5f"
GRAPHITE_SUCCESS = "#7fb087"
GRAPHITE_SUCCESS_DARK = "#41684a"
GRAPHITE_READY = "#4d657f"
GRAPHITE_BUILDING = "#7f5f3a"
GRAPHITE_ERROR = "#ff7070"
GRAPHITE_ERROR_DARK = "#7f3434"

ZERO = bytes([0])
WIN_SEP = chr(92)
COPY_CHUNK_SIZE = 1024 * 1024

TEMP_MARKER_FILE = ".pbo_builder_byraizo_temp"
BUILDER_TEMP_CHILDREN = {
    "addons",
    "preflight",
    "staging",
    "binarized",
    "configs",
    "_binarize_textures",
}
