import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .constants import DEFAULT_PROJECT_ROOT, DEFAULT_TEMP_DIR, WIN_SEP
from .filters import parse_exclude_patterns, should_skip_dir, should_skip_file
from .system import get_hidden_startupinfo, get_subprocess_creationflags
from .targets import format_duration, get_pbo_prefix, get_safe_temp_name, read_pbo_prefix_file
from .tools import normalize_working_dir

REFERENCE_EXTENSIONS = (
    ".paa",
    ".rvmat",
    ".p3d",
    ".wrp",
    ".wss",
    ".ogg",
    ".wav",
    ".cfg",
    ".cpp",
    ".hpp",
    ".h",
    ".emat",
    ".edds",
    ".ptc",
    ".bisurf",
    ".shp",
    ".dbf",
    ".shx",
    ".prj",
)
PREFLIGHT_TEXT_EXTENSIONS = (
    ".cpp",
    ".hpp",
    ".h",
    ".rvmat",
    ".cfg",
    ".c",
    ".xml",
    ".json",
    ".layout",
    ".imageset",
)
REFERENCE_REGEX = re.compile(
    r"[\"']([^\"']+\.(?:paa|rvmat|p3d|wrp|wss|ogg|wav|cfg|cpp|hpp|h|emat|edds|ptc|bisurf|shp|dbf|shx|prj))[\"']",
    re.IGNORECASE,
)
RVMAT_TEXTURE_REGEX = re.compile(
    r"\btexture\s*=\s*[\"]?([^\";\r\n]+\.(?:paa|png|tga|psd|rvmat|emat|edds|ptc))[\"]?",
    re.IGNORECASE,
)
P3D_INTERNAL_REFERENCE_REGEX = re.compile(
    rb"([A-Za-z0-9_@#$%&()\-+={}\[\],.;: /\\]+\.(?:paa|rvmat|p3d|wrp|emat|edds|ptc|bisurf|shp|dbf|shx|prj))",
    re.IGNORECASE,
)
SOURCE_EXPORT_DIR_NAMES = {"source", "sources", "export", "exports", "terrainbuilder", "tb"}
SOURCE_EXPORT_EXTENSIONS = {
    ".pew",
    ".tv4p",
    ".tv4l",
    ".asc",
    ".xyz",
    ".raw",
    ".tif",
    ".tiff",
    ".psd",
    ".png",
    ".tga",
    ".lbt",
}
ROAD_SHAPE_SIDECARS = (".dbf", ".shx", ".prj")
SCRIPT_MODULE_DIRS = ("3_Game", "4_World", "5_Mission")
PREFLIGHT_CHECK_DEFAULTS = {
    "preflight_check_cfgpatches": True,
    "preflight_check_required_addons": True,
    "preflight_check_cfgmods": True,
    "preflight_check_references": True,
    "preflight_check_p3d_internal": True,
    "preflight_check_case_conflicts": True,
    "preflight_check_risky_paths": True,
    "preflight_check_prefix": True,
    "preflight_check_terrain_wrp": True,
    "preflight_check_terrain_navmesh": False,
    "preflight_check_terrain_road_shapes": True,
    "preflight_check_terrain_layers": True,
    "preflight_check_terrain_source_exports": True,
    "preflight_check_terrain_size": True,
}


class PreflightResult:
    def __init__(self):
        self.errors = 0
        self.warnings = 0
        self.notes = 0
        self.checked_files = 0
        self.checked_references = 0
        self.messages = []

    def _record(self, severity, log, message):
        self.messages.append(
            {
                "severity": severity,
                "message": message,
            }
        )
        log(f"{severity}: {message}")

    def error(self, log, message):
        self.errors += 1
        self._record("ERROR", log, message)

    def warning(self, log, message):
        self.warnings += 1
        self._record("WARNING", log, message)

    def note(self, log, message):
        self.notes += 1
        self._record("INFO", log, message)


def get_preflight_check_settings(settings):
    return {key: bool(settings.get(key, default)) for key, default in PREFLIGHT_CHECK_DEFAULTS.items()}


def normalize_reference_path(reference):
    value = reference.strip().strip('"').strip("'")
    value = value.replace("/", WIN_SEP)
    value = re.sub(r"^\{[0-9A-Fa-f-]{8,}\}", "", value)
    while value.startswith(WIN_SEP):
        value = value[1:]
    return value


def format_source_location(file_path, addon_source_dir, line_number=None):
    rel_file = os.path.relpath(file_path, addon_source_dir).replace(os.sep, WIN_SEP)
    if line_number:
        return f"{rel_file}: line {line_number}"
    return rel_file


def find_case_mismatch(path):
    normalized = os.path.normpath(path)
    drive, rest = os.path.splitdrive(normalized)
    if not rest:
        return ""
    parts = [part for part in rest.replace("/", WIN_SEP).split(WIN_SEP) if part]
    current = drive + WIN_SEP if drive else (WIN_SEP if normalized.startswith(WIN_SEP) else "")
    for part in parts:
        parent = current if current else "."
        try:
            entries = os.listdir(parent)
        except Exception:
            return ""
        exact = part in entries
        lower_match = ""
        if not exact:
            part_lower = part.lower()
            for entry in entries:
                if entry.lower() == part_lower:
                    lower_match = entry
                    break
        if lower_match:
            return f"expected '{lower_match}', referenced '{part}' in {normalized}"
        current = os.path.join(current, part) if current else part
    return ""


def resolve_reference_path(reference, addon_source_dir, project_root):
    ref = normalize_reference_path(reference)
    if not ref:
        return "", "missing"
    candidates = []
    if os.path.isabs(ref):
        candidates.append(ref)
    addon_source_dir = os.path.normpath(addon_source_dir)
    addon_parent = os.path.dirname(addon_source_dir)
    candidates.append(os.path.join(addon_source_dir, ref))
    candidates.append(os.path.join(addon_parent, ref))
    if project_root:
        project_root_normalized = normalize_working_dir(project_root)
        candidates.append(os.path.join(project_root_normalized, ref))
    seen = set()
    for candidate in candidates:
        candidate = os.path.normpath(candidate)
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(candidate):
            mismatch = find_case_mismatch(candidate)
            if mismatch:
                return candidate, "case_mismatch:" + mismatch
            return candidate, "ok"
    return candidates[0] if candidates else ref, "missing"


def path_is_excluded(path_value, root_dir, extra_patterns=None):
    try:
        rel = os.path.relpath(path_value, root_dir)
    except ValueError:
        return False
    if rel.startswith(".."):
        return False
    parts = rel.replace("/", WIN_SEP).split(WIN_SEP)
    for dirname in parts[:-1]:
        if should_skip_dir(dirname, extra_patterns):
            return True
    return should_skip_file(parts[-1], extra_patterns)


def iter_preflight_text_files(source_dir, extra_patterns=None):
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if should_skip_file(file, extra_patterns):
                continue
            ext = os.path.splitext(file)[1].lower()
            if ext in PREFLIGHT_TEXT_EXTENSIONS:
                yield os.path.join(root, file)


def iter_p3d_files(source_dir, extra_patterns=None):
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if file.lower().endswith(".p3d") and not should_skip_file(file, extra_patterns):
                yield os.path.join(root, file)


def iter_files_by_extension(source_dir, extensions, extra_patterns=None):
    extensions = {ext.lower() for ext in extensions}
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if should_skip_file(file, extra_patterns):
                continue
            if os.path.splitext(file)[1].lower() in extensions:
                yield os.path.join(root, file)


def collect_config_cpp_files(source_dir, extra_patterns=None):
    configs = []
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if file.lower() == "config.cpp":
                configs.append(os.path.join(root, file))
    configs.sort(key=lambda path: os.path.relpath(path, source_dir).lower())
    return configs


def read_text_file(path):
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def strip_config_comments(content):
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    content = re.sub(r"//.*", "", content)
    return content


def find_class_block(content, class_name):
    pattern = re.compile(r"\bclass\s+" + re.escape(class_name) + r"\b[^{;]*\{", re.IGNORECASE)
    match = pattern.search(content)
    if not match:
        return ""
    start = match.end()
    depth = 1
    index = start
    while index < len(content):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start:index]
        index += 1
    return ""


def find_config_classes(content):
    return re.findall(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b(?:\s*:\s*([A-Za-z_][A-Za-z0-9_]*))?", content)


def parse_required_addons(block):
    match = re.search(r"\brequiredAddons\s*\[\]\s*=\s*\{([^}]*)\}", block, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return [item.strip().strip('"').strip("'") for item in match.group(1).split(",") if item.strip()]


def preflight_check_config_cpp(config_cpp, cfgconvert_exe, temp_root, addon_name, result, log):
    if not cfgconvert_exe or not os.path.isfile(cfgconvert_exe):
        result.warning(log, "CfgConvert.exe is not configured. Skipping config.cpp syntax check.")
        return
    rel_name = os.path.basename(config_cpp)
    safe_addon = get_safe_temp_name(addon_name)
    check_dir = os.path.join(temp_root, "preflight", safe_addon)
    os.makedirs(check_dir, exist_ok=True)
    output_bin = os.path.join(check_dir, rel_name + ".bin")
    if os.path.isfile(output_bin):
        os.remove(output_bin)
    cmd = [cfgconvert_exe, "-bin", "-dst", output_bin, config_cpp]
    completed = subprocess.run(
        cmd,
        cwd=os.path.dirname(config_cpp),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=get_subprocess_creationflags(),
        startupinfo=get_hidden_startupinfo(),
    )
    if completed.returncode != 0 or not os.path.isfile(output_bin):
        output = completed.stdout.strip() if completed.stdout else "No CfgConvert output."
        result.error(log, f"Config syntax check failed: {config_cpp}")
        for line in output.splitlines():
            log("  " + line)
        return
    log(f"Config syntax OK: {config_cpp}")


def preflight_check_cfgpatches(config_cpp, addon_source_dir, result, log, check_required_addons=True):
    try:
        content = strip_config_comments(read_text_file(config_cpp))
    except Exception as e:
        result.warning(log, f"Could not read config.cpp for CfgPatches check: {config_cpp} ({e})")
        return

    location = format_source_location(config_cpp, addon_source_dir)
    block = find_class_block(content, "CfgPatches")
    if not block:
        severity = (
            result.error
            if os.path.normcase(os.path.abspath(config_cpp))
            == os.path.normcase(os.path.abspath(os.path.join(addon_source_dir, "config.cpp")))
            else result.warning
        )
        severity(log, f"CfgPatches class not found in {location}.")
        return

    patch_classes = find_config_classes(block)
    if not patch_classes:
        result.error(log, f"CfgPatches has no addon classes in {location}.")
        return

    for class_name, _base in patch_classes:
        class_block = find_class_block(block, class_name)
        if check_required_addons:
            required = parse_required_addons(class_block)
            if required is None:
                result.warning(log, f"requiredAddons[] is missing in CfgPatches class {class_name} ({location}).")
            elif not required:
                inherited_classes = [
                    base for _, base in find_config_classes(content) if base and base not in {"Default"}
                ]
                if inherited_classes:
                    result.warning(
                        log,
                        f"requiredAddons[] is empty in {class_name}, but config appears to inherit from external classes.",
                    )
                else:
                    result.note(log, f"requiredAddons[] is empty in {class_name}.")


def preflight_check_cfgmods(configs, addon_source_dir, project_root, result, log):
    script_paths = []
    scripts_root = os.path.join(addon_source_dir, "scripts")
    for module_dir in SCRIPT_MODULE_DIRS:
        module_path = os.path.join(scripts_root, module_dir)
        if os.path.isdir(module_path):
            script_paths.append((module_dir, module_path))
    if not script_paths:
        return

    combined = ""
    for config_cpp in configs:
        try:
            combined += "\n" + strip_config_comments(read_text_file(config_cpp))
        except Exception:
            continue

    cfgmods = find_class_block(combined, "CfgMods")
    if not cfgmods:
        result.warning(log, "scripts folder exists, but CfgMods was not found in addon configs.")
        return

    for module_dir, module_path in script_paths:
        if module_dir not in cfgmods:
            result.warning(log, f"Script module folder exists but is not referenced in CfgMods: scripts\\{module_dir}")
            continue
        result.note(log, f"CfgMods script module reference found for scripts\\{module_dir}.")


def preflight_check_prefix(addon_name, addon_source_dir, result, log):
    prefix_names = {"$pboprefix$", "$prefix$", "$pboprefix$.txt", "$prefix$.txt"}
    try:
        entries = os.listdir(addon_source_dir)
    except OSError:
        return
    found = [
        entry
        for entry in entries
        if entry.lower() in prefix_names and os.path.isfile(os.path.join(addon_source_dir, entry))
    ]
    if len(found) > 1:
        result.warning(log, f"Multiple PBO prefix files found in {addon_name}: {', '.join(found)}")

    prefix = read_pbo_prefix_file(addon_source_dir)
    if not prefix:
        result.note(log, f"No explicit PBO prefix file found. Fallback prefix will be addon/PBO name: {addon_name}")
        return

    if re.match(r"^[A-Za-z]:", prefix):
        result.warning(log, f"PBO prefix looks like a drive path: {prefix}")
    if prefix.startswith((WIN_SEP, "/")) or prefix.endswith((WIN_SEP, "/")):
        result.warning(log, f"PBO prefix has leading/trailing slash: {prefix}")
    if "/" in prefix:
        result.warning(log, f"PBO prefix contains forward slashes. Use backslashes for DayZ paths: {prefix}")


def preflight_scan_references(file_path, addon_source_dir, project_root, extra_patterns, result, log):
    try:
        lines = Path(file_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as e:
        result.warning(log, f"Could not read file for reference scan: {file_path} ({e})")
        return
    result.checked_files += 1
    seen_refs = set()
    for line_number, line in enumerate(lines, start=1):
        matches = list(REFERENCE_REGEX.finditer(line))
        if os.path.splitext(file_path)[1].lower() == ".rvmat":
            matches.extend(RVMAT_TEXTURE_REGEX.finditer(line))
        for match in matches:
            reference = match.group(1).strip()
            normalized_ref = normalize_reference_path(reference)
            ref_key = (normalized_ref.lower(), line_number)
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)
            result.checked_references += 1
            resolved, status = resolve_reference_path(normalized_ref, addon_source_dir, project_root)
            location = format_source_location(file_path, addon_source_dir, line_number)
            if status == "missing":
                result.error(log, f"Missing referenced file in {location}: {normalized_ref}")
            elif status.startswith("case_mismatch:"):
                continue
            elif path_is_excluded(resolved, addon_source_dir, extra_patterns):
                result.warning(
                    log, f"Referenced file exists but is excluded from final PBO in {location}: {normalized_ref}"
                )


def preflight_scan_p3d_internal_references(p3d_file, addon_source_dir, project_root, extra_patterns, result, log):
    rel_file = os.path.relpath(p3d_file, addon_source_dir).replace(os.sep, WIN_SEP)
    try:
        data = Path(p3d_file).read_bytes()
    except Exception as e:
        result.warning(log, f"Could not read P3D for internal reference scan: {rel_file} ({e})")
        return
    result.checked_files += 1
    seen_refs = set()
    found_refs = 0
    for match in P3D_INTERNAL_REFERENCE_REGEX.finditer(data):
        reference = match.group(1).decode("ascii", errors="ignore").strip()
        normalized_ref = normalize_reference_path(reference)
        ref_key = normalized_ref.lower()
        if not normalized_ref or ref_key in seen_refs or len(normalized_ref) < 5:
            continue
        seen_refs.add(ref_key)
        found_refs += 1
        result.checked_references += 1
        resolved, status = resolve_reference_path(normalized_ref, addon_source_dir, project_root)
        if status == "missing":
            result.warning(log, f"Missing internal P3D reference in {rel_file}: {normalized_ref}")
        elif status.startswith("case_mismatch:"):
            continue
        elif path_is_excluded(resolved, addon_source_dir, extra_patterns):
            result.warning(
                log, f"Internal P3D reference exists but is excluded from final PBO in {rel_file}: {normalized_ref}"
            )
    if found_refs:
        log(f"P3D internal scan checked {found_refs} reference(s): {rel_file}")


def preflight_scan_case_conflicts(addon_source_dir, extra_patterns, result, log):
    seen = {}
    for root, dirs, files in os.walk(addon_source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for name in dirs + files:
            path = os.path.join(root, name)
            if os.path.isfile(path) and should_skip_file(name, extra_patterns):
                continue
            rel = os.path.relpath(path, addon_source_dir).replace(os.sep, WIN_SEP)
            key = rel.lower()
            previous = seen.get(key)
            if previous and previous != rel:
                result.warning(log, f"Case-only path conflict: {previous} <-> {rel}")
            else:
                seen[key] = rel


def preflight_scan_risky_paths(addon_source_dir, extra_patterns, result, log):
    risky_chars = set('<>:"|?*')
    for root, dirs, files in os.walk(addon_source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for name in dirs + files:
            if os.path.isfile(os.path.join(root, name)) and should_skip_file(name, extra_patterns):
                continue
            if any(char in name for char in risky_chars) or name != name.strip():
                rel = os.path.relpath(os.path.join(root, name), addon_source_dir).replace(os.sep, WIN_SEP)
                result.warning(log, f"Risky file/folder name: {rel}")


def collect_wrp_files(addon_source_dir, extra_patterns):
    return list(iter_files_by_extension(addon_source_dir, {".wrp"}, extra_patterns))


def preflight_check_terrain_wrp(
    addon_name, addon_source_dir, config_files, project_root, extra_patterns, result, log, checks
):
    wrp_files = collect_wrp_files(addon_source_dir, extra_patterns)
    if not wrp_files:
        return

    result.note(log, f"Terrain/WRP addon detected: {addon_name} ({len(wrp_files)} .wrp file(s))")
    prefix = get_pbo_prefix(addon_name, addon_source_dir)
    if not read_pbo_prefix_file(addon_source_dir):
        result.warning(
            log,
            f"Terrain/WRP addon has no explicit PBO prefix file. A $PBOPREFIX$ file is strongly recommended: {addon_name}",
        )

    combined = ""
    for config_cpp in config_files:
        try:
            combined += "\n" + strip_config_comments(read_text_file(config_cpp))
        except Exception:
            continue

    if "CfgWorlds" not in combined:
        result.warning(log, "WRP exists, but CfgWorlds was not found in addon configs.")
    if "CfgWorldList" not in combined and "CfgWorldsList" not in combined:
        result.warning(log, "WRP exists, but CfgWorldList/CfgWorldsList was not found in addon configs.")

    world_names = re.findall(r"\bworldName\s*=\s*[\"']([^\"']+\.wrp)[\"']", combined, flags=re.IGNORECASE)
    if not world_names:
        result.warning(log, 'WRP exists, but no worldName="...wrp" was found.')
    for world_name in world_names:
        normalized = normalize_reference_path(world_name)
        resolved, status = resolve_reference_path(normalized, addon_source_dir, project_root)
        if status == "missing":
            result.error(log, f"worldName points to missing WRP: {normalized}")
        if prefix and not normalized.lower().startswith(prefix.lower() + WIN_SEP):
            result.warning(
                log,
                f"worldName path does not start with detected PBO prefix: prefix '{prefix}', worldName '{normalized}'",
            )

    if len(wrp_files) > 1:
        listed = ", ".join(os.path.relpath(path, addon_source_dir).replace(os.sep, WIN_SEP) for path in wrp_files)
        result.warning(log, f"Multiple WRP files found. Check for stale terrain exports: {listed}")

    if checks["preflight_check_terrain_navmesh"]:
        preflight_check_navmesh(addon_source_dir, extra_patterns, result, log)
    else:
        result.note(log, "Terrain navmesh check disabled.")
    if checks["preflight_check_terrain_road_shapes"]:
        preflight_check_road_shapes(addon_source_dir, extra_patterns, result, log)
    else:
        result.note(log, "Terrain road/shape check disabled.")
    if checks["preflight_check_terrain_layers"]:
        preflight_check_terrain_layers(addon_source_dir, project_root, extra_patterns, result, log)
    else:
        result.note(log, "Terrain layer check disabled.")
    if checks["preflight_check_terrain_source_exports"]:
        preflight_check_source_exports(addon_source_dir, extra_patterns, result, log)
    else:
        result.note(log, "Terrain source/export warning check disabled.")
    if checks["preflight_check_terrain_size"]:
        preflight_check_terrain_size(addon_source_dir, extra_patterns, result, log)
    else:
        result.note(log, "Terrain size check disabled.")


def preflight_check_navmesh(addon_source_dir, extra_patterns, result, log):
    navmesh_dirs = []
    for root, dirs, _files in os.walk(addon_source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for dirname in dirs:
            if dirname.lower() == "navmesh":
                navmesh_dirs.append(os.path.join(root, dirname))
    if not navmesh_dirs:
        result.warning(log, "Terrain navmesh folder was not found.")
        return
    for navmesh_dir in navmesh_dirs:
        included_files = []
        for root, dirs, files in os.walk(navmesh_dir):
            dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
            for file in files:
                if not should_skip_file(file, extra_patterns):
                    included_files.append(os.path.join(root, file))
        rel = os.path.relpath(navmesh_dir, addon_source_dir).replace(os.sep, WIN_SEP)
        if not included_files:
            result.warning(log, f"Navmesh folder is empty or fully excluded: {rel}")
        else:
            result.note(log, f"Navmesh folder detected: {rel} ({len(included_files)} included file(s))")


def preflight_check_road_shapes(addon_source_dir, extra_patterns, result, log):
    for shp in iter_files_by_extension(addon_source_dir, {".shp"}, extra_patterns):
        base, _ = os.path.splitext(shp)
        rel = os.path.relpath(shp, addon_source_dir).replace(os.sep, WIN_SEP)
        for ext in ROAD_SHAPE_SIDECARS:
            sidecar = base + ext
            if not os.path.isfile(sidecar):
                result.warning(log, f"Road shape file exists but matching {ext} sidecar is missing: {rel}")
            elif path_is_excluded(sidecar, addon_source_dir, extra_patterns):
                result.warning(log, f"Road shape sidecar is excluded from final PBO: {rel}{ext}")


def preflight_check_terrain_layers(addon_source_dir, project_root, extra_patterns, result, log):
    layer_dirs = []
    for root, dirs, _files in os.walk(addon_source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for dirname in dirs:
            if dirname.lower() in {"layers", "data"}:
                layer_dirs.append(os.path.join(root, dirname))
    for layer_dir in layer_dirs:
        rvmat_files = list(iter_files_by_extension(layer_dir, {".rvmat"}, extra_patterns))
        rel_dir = os.path.relpath(layer_dir, addon_source_dir).replace(os.sep, WIN_SEP)
        if not rvmat_files and os.path.basename(layer_dir).lower() == "layers":
            result.warning(log, f"Terrain layers folder contains no .rvmat files: {rel_dir}")
        for rvmat in rvmat_files:
            preflight_scan_references(rvmat, addon_source_dir, project_root, extra_patterns, result, log)


def preflight_check_source_exports(addon_source_dir, extra_patterns, result, log):
    warned = 0
    for root, dirs, files in os.walk(addon_source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for dirname in dirs:
            if dirname.lower() in SOURCE_EXPORT_DIR_NAMES:
                rel = os.path.relpath(os.path.join(root, dirname), addon_source_dir).replace(os.sep, WIN_SEP)
                result.warning(log, f"Terrain source/export folder may be packed into release PBO: {rel}")
                warned += 1
        for file in files:
            if should_skip_file(file, extra_patterns):
                continue
            ext = os.path.splitext(file)[1].lower()
            if ext in SOURCE_EXPORT_EXTENSIONS:
                rel = os.path.relpath(os.path.join(root, file), addon_source_dir).replace(os.sep, WIN_SEP)
                result.warning(log, f"Terrain source/export file may be packed into release PBO: {rel}")
                warned += 1
                if warned >= 25:
                    result.warning(log, "Additional terrain source/export warnings suppressed.")
                    return


def format_size(size):
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def preflight_check_terrain_size(addon_source_dir, extra_patterns, result, log):
    sizes = {}
    total = 0
    for root, dirs, files in os.walk(addon_source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if should_skip_file(file, extra_patterns):
                continue
            path = os.path.join(root, file)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            rel = os.path.relpath(path, addon_source_dir)
            top = rel.split(os.sep, 1)[0] if os.sep in rel else "."
            sizes[top] = sizes.get(top, 0) + size
            total += size
    result.note(log, f"Terrain size estimate: total={format_size(total)}")
    for top, size in sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:12]:
        suffix = " WARNING" if top.lower() in SOURCE_EXPORT_DIR_NAMES else ""
        result.note(log, f"  {top}: {format_size(size)}{suffix}")


def get_preflight_report_paths(log_file):
    if log_file:
        base = Path(log_file).with_suffix("")
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path.cwd() / f"preflight_{stamp}"
    return base.with_suffix(".preflight.txt"), base.with_suffix(".preflight.json")


def export_preflight_report(settings, targets, result, elapsed, log):
    txt_path, json_path = get_preflight_report_paths(settings.get("log_file", ""))
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "summary": {
            "addons": len(targets),
            "scanned_files": result.checked_files,
            "checked_references": result.checked_references,
            "errors": result.errors,
            "warnings": result.warnings,
            "notes": result.notes,
            "elapsed_seconds": round(elapsed, 3),
        },
        "targets": [{"name": name, "path": path} for name, path in targets],
        "messages": result.messages,
    }
    lines = [
        "Preflight report",
        "=" * 80,
        f"Addons:             {len(targets)}",
        f"Scanned files:      {result.checked_files}",
        f"Checked references: {result.checked_references}",
        f"Errors:             {result.errors}",
        f"Warnings:           {result.warnings}",
        f"Notes:              {result.notes}",
        f"Time:               {format_duration(elapsed)}",
        "",
    ]
    for message in result.messages:
        lines.append(f"{message['severity']}: {message['message']}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Preflight report saved: {txt_path}")
    log(f"Preflight report JSON saved: {json_path}")


def run_preflight_for_targets(settings, targets, log, progress_callback=None):
    start_time = time.time()
    result = PreflightResult()
    cfgconvert_exe = settings.get("cfgconvert_exe", "")
    temp_root = settings.get("temp_dir", DEFAULT_TEMP_DIR)
    project_root = settings.get("project_root", DEFAULT_PROJECT_ROOT)
    extra_patterns = parse_exclude_patterns(settings.get("exclude_patterns", ""))
    checks = get_preflight_check_settings(settings)
    log("")
    log("=" * 80)
    log("DayZ Preflight Check")
    log("=" * 80)
    for index, (addon_name, addon_source_dir) in enumerate(targets, start=1):
        if progress_callback:
            progress_callback(index - 1, len(targets))
        log("")
        log(f"Checking addon {index}/{len(targets)}: {addon_name}")

        if checks["preflight_check_prefix"]:
            preflight_check_prefix(addon_name, addon_source_dir, result, log)
        else:
            result.note(log, "Prefix check disabled.")
        if checks["preflight_check_case_conflicts"]:
            preflight_scan_case_conflicts(addon_source_dir, extra_patterns, result, log)
        else:
            result.note(log, "Case-only path conflict check disabled.")
        if checks["preflight_check_risky_paths"]:
            preflight_scan_risky_paths(addon_source_dir, extra_patterns, result, log)
        else:
            result.note(log, "Risky filename/path check disabled.")

        config_files = collect_config_cpp_files(addon_source_dir, extra_patterns)
        if config_files:
            log(f"Found {len(config_files)} config.cpp file(s).")
            for config_cpp in config_files:
                preflight_check_config_cpp(config_cpp, cfgconvert_exe, temp_root, addon_name, result, log)
                if checks["preflight_check_cfgpatches"]:
                    preflight_check_cfgpatches(
                        config_cpp,
                        addon_source_dir,
                        result,
                        log,
                        checks["preflight_check_required_addons"],
                    )
                else:
                    result.note(log, "CfgPatches check disabled.")
            if checks["preflight_check_cfgmods"]:
                preflight_check_cfgmods(config_files, addon_source_dir, project_root, result, log)
            else:
                result.note(log, "CfgMods script module check disabled.")
        else:
            result.warning(log, f"No included config.cpp found in addon source: {addon_source_dir}")

        if checks["preflight_check_terrain_wrp"]:
            preflight_check_terrain_wrp(
                addon_name, addon_source_dir, config_files, project_root, extra_patterns, result, log, checks
            )
        else:
            result.note(log, "Terrain/WRP check disabled.")

        if checks["preflight_check_references"]:
            for text_file in iter_preflight_text_files(addon_source_dir, extra_patterns):
                preflight_scan_references(text_file, addon_source_dir, project_root, extra_patterns, result, log)
        else:
            result.note(log, "Text reference scan disabled.")
        if checks["preflight_check_p3d_internal"]:
            for p3d_file in iter_p3d_files(addon_source_dir, extra_patterns):
                preflight_scan_p3d_internal_references(
                    p3d_file, addon_source_dir, project_root, extra_patterns, result, log
                )
        else:
            result.note(log, "P3D internal reference scan disabled.")
    if progress_callback:
        progress_callback(len(targets), len(targets))
    elapsed = time.time() - start_time
    log("")
    log("=" * 80)
    log("Preflight summary")
    log("=" * 80)
    log(f"Addons:             {len(targets)}")
    log(f"Scanned files:      {result.checked_files}")
    log(f"Checked references: {result.checked_references}")
    log(f"Errors:             {result.errors}")
    log(f"Warnings:           {result.warnings}")
    log(f"Notes:              {result.notes}")
    log(f"Time:               {format_duration(elapsed)}")
    log("=" * 80)
    try:
        export_preflight_report(settings, targets, result, elapsed, log)
    except Exception as e:
        result.warning(log, f"Could not export preflight report: {e}")
    return result
