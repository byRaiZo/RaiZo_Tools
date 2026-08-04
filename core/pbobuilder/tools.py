import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import junction
from .constants import WIN_SEP
from .errors import BuildError
from .filters import (
    get_p3d_magic,
    has_paa_files,
    is_binarized_p3d,
    should_skip_dir,
    should_skip_file,
)
from .files import overlay_tree
from .system import get_hidden_startupinfo, get_subprocess_creationflags
from .targets import get_safe_temp_name

P3D_BINARIZE_REFERENCE_REGEX = re.compile(
    rb"([A-Za-z0-9_@#$%&()\-+={}\[\],.;: /\\]+\.(?:paa|rvmat|p3d|emat|edds|ptc|cfg))",
    re.IGNORECASE,
)
DEFAULT_ISOLATED_DEPENDENCY_ROOTS = ("DZ", "bin")
ISOLATED_DEPENDENCY_LINKS_FILE = ".pbo_builder_dependency_links.json"


def normalize_project_root_arg(project_root):
    return project_root.rstrip(WIN_SEP + "/")


def normalize_working_dir(project_root):
    value = project_root.rstrip(WIN_SEP + "/")
    if len(value) == 2 and value[1] == ":":
        return value + WIN_SEP
    return value


def run_logged_subprocess(cmd, cwd, log):
    output_lines = []
    process = subprocess.Popen(
        cmd,
        cwd=cwd if cwd and os.path.isdir(cwd) else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        creationflags=get_subprocess_creationflags(),
        startupinfo=get_hidden_startupinfo(),
    )
    if process.stdout:
        for line in process.stdout:
            line = line.rstrip("\r\n")
            output_lines.append(line)
            log(line)
    returncode = process.wait()
    return subprocess.CompletedProcess(cmd, returncode, "\n".join(output_lines))


def same_path(left, right):
    try:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
    except OSError:
        return False


def normalize_p3d_reference_root(reference):
    value = reference.replace("/", WIN_SEP).strip()
    if not value:
        return ""
    value = value.strip("\x00 \t\r\n\"'")
    if any(char.isspace() for char in value):
        tokens = value.split()
        if tokens:
            value = tokens[-1]
    if len(value) > 2 and value[1] == ":":
        value = value[2:].lstrip(WIN_SEP)
    value = value.lstrip(WIN_SEP)
    if not value or value.startswith("."):
        return ""
    parts = [part for part in value.split(WIN_SEP) if part]
    if len(parts) < 2:
        return ""
    root = parts[0].strip()
    if not root or root in {".", ".."}:
        return ""
    return root


def collect_p3d_dependency_roots(source_dir):
    roots = set()
    if not os.path.isdir(source_dir):
        return roots

    for walk_root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        for file_name in files:
            if not file_name.lower().endswith(".p3d"):
                continue
            p3d_path = os.path.join(walk_root, file_name)
            try:
                with open(p3d_path, "rb") as p3d_file:
                    data = p3d_file.read()
            except OSError:
                continue

            for match in P3D_BINARIZE_REFERENCE_REGEX.finditer(data):
                try:
                    reference = match.group(1).decode("ascii", errors="ignore")
                except UnicodeDecodeError:
                    continue
                root = normalize_p3d_reference_root(reference)
                if root:
                    roots.add(root)

    return roots


def find_project_child_dir(project_root, child_name):
    if not project_root or not child_name:
        return ""
    root = normalize_working_dir(project_root)
    direct = os.path.join(root, child_name)
    if os.path.isdir(direct):
        return direct

    try:
        child_lower = child_name.lower()
        for existing in os.listdir(root):
            if existing.lower() == child_lower:
                candidate = os.path.join(root, existing)
                if os.path.isdir(candidate):
                    return candidate
    except OSError:
        pass

    return ""


def link_dependency_dir(link_path, target_path, log):
    if os.path.exists(link_path):
        return True
    os.makedirs(os.path.dirname(link_path), exist_ok=True)

    junction_error = junction.create(Path(link_path), Path(target_path))
    if not junction_error:
        return True

    try:
        os.symlink(target_path, link_path, target_is_directory=True)
        return True
    except OSError as symlink_error:
        log(f"WARNING: Could not create dependency junction: {junction_error}")
        log(f"WARNING: Could not create dependency symlink: {link_path} -> {target_path} ({symlink_error})")
        return False


def remove_isolated_binarize_project(isolated_root, log=None):
    if not isolated_root or not os.path.isdir(isolated_root):
        return

    links_file = os.path.join(isolated_root, ISOLATED_DEPENDENCY_LINKS_FILE)
    if os.path.isfile(links_file):
        try:
            with open(links_file, "r", encoding="utf-8") as file:
                link_paths = json.load(file)
        except (OSError, json.JSONDecodeError):
            link_paths = []

        for link_path in link_paths:
            if not link_path:
                continue
            try:
                if os.path.isdir(link_path):
                    os.rmdir(link_path)
            except OSError as error:
                if log:
                    log(f"WARNING: Could not remove isolated dependency link: {link_path} ({error})")

        try:
            os.remove(links_file)
        except OSError:
            pass

    shutil.rmtree(isolated_root)


def create_isolated_binarize_source(source_dir, temp_dir, addon_name, project_root, log):
    safe_addon = get_safe_temp_name(addon_name or os.path.basename(os.path.normpath(source_dir)) or "addon")
    isolated_root = os.path.join(temp_dir, "addons", safe_addon, "isolated_binarize_project")
    isolated_source = os.path.join(isolated_root, safe_addon)
    if os.path.isdir(isolated_root):
        remove_isolated_binarize_project(isolated_root, log)
    os.makedirs(isolated_root, exist_ok=True)
    log(f"Preparing isolated Binarize project root: {isolated_root}")
    shutil.copytree(source_dir, isolated_source)

    dependency_root_map = {}
    for dependency_root in DEFAULT_ISOLATED_DEPENDENCY_ROOTS:
        dependency_root_map.setdefault(dependency_root.lower(), dependency_root)
    for dependency_root in collect_p3d_dependency_roots(source_dir):
        dependency_root_map.setdefault(dependency_root.lower(), dependency_root)
    dependency_root_map.pop(safe_addon.lower(), None)
    dependency_root_map.pop(os.path.basename(os.path.normpath(source_dir)).lower(), None)

    linked = []
    linked_paths = []
    missing = []
    for dependency_root in sorted(dependency_root_map.values(), key=str.lower):
        if os.path.isdir(os.path.join(source_dir, dependency_root)):
            continue
        target_dir = find_project_child_dir(project_root, dependency_root)
        if not target_dir:
            missing.append(dependency_root)
            continue
        if same_path(target_dir, source_dir):
            continue
        link_name = os.path.basename(os.path.normpath(target_dir))
        link_path = os.path.join(isolated_root, link_name)
        if same_path(link_path, isolated_source):
            continue
        if link_dependency_dir(link_path, target_dir, log):
            linked.append(f"{link_name} -> {target_dir}")
            linked_paths.append(link_path)

    if linked_paths:
        links_file = os.path.join(isolated_root, ISOLATED_DEPENDENCY_LINKS_FILE)
        try:
            with open(links_file, "w", encoding="utf-8") as file:
                json.dump(linked_paths, file, indent=2)
        except OSError as error:
            log(f"WARNING: Could not write isolated dependency link manifest: {links_file} ({error})")

    if linked:
        log("Linked isolated Binarize dependency roots:")
        for item in linked:
            log(f"  {item}")
    if missing:
        log("WARNING: Some P3D dependency roots were referenced but not found under project root:")
        for item in missing:
            log(f"  {item}")

    return isolated_root, isolated_source


def find_dayz_binarize():
    possible_paths = [
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Steam/steamapps/common/DayZ Tools/Bin/Binarize/binarize.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Steam/steamapps/common/DayZ Tools/Bin/Binarize/binarize.exe",
        Path("C:/Program Files (x86)/Steam/steamapps/common/DayZ Tools/Bin/Binarize/binarize.exe"),
        Path("C:/Program Files/Steam/steamapps/common/DayZ Tools/Bin/Binarize/binarize.exe"),
    ]
    for path in possible_paths:
        if path.is_file():
            return str(path)
    return ""


def find_cfgconvert():
    possible_paths = [
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Steam/steamapps/common/DayZ Tools/Bin/CfgConvert/CfgConvert.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Steam/steamapps/common/DayZ Tools/Bin/CfgConvert/CfgConvert.exe",
        Path("C:/Program Files (x86)/Steam/steamapps/common/DayZ Tools/Bin/CfgConvert/CfgConvert.exe"),
        Path("C:/Program Files/Steam/steamapps/common/DayZ Tools/Bin/CfgConvert/CfgConvert.exe"),
    ]
    for path in possible_paths:
        if path.is_file():
            return str(path)
    return ""


def find_dssignfile():
    possible_paths = [
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Steam/steamapps/common/DayZ Tools/Bin/DSUtils/DSSignFile.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Steam/steamapps/common/DayZ Tools/Bin/DSUtils/DSSignFile.exe",
        Path("C:/Program Files (x86)/Steam/steamapps/common/DayZ Tools/Bin/DSUtils/DSSignFile.exe"),
        Path("C:/Program Files/Steam/steamapps/common/DayZ Tools/Bin/DSUtils/DSSignFile.exe"),
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Steam/steamapps/common/DayZ Tools/Bin/DSSignFile/DSSignFile.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Steam/steamapps/common/DayZ Tools/Bin/DSSignFile/DSSignFile.exe",
    ]
    for path in possible_paths:
        if path.is_file():
            return str(path)
    return ""


def find_p3d_obfuscator():
    repo_root = Path(__file__).resolve().parents[2]
    possible_paths = [
        repo_root / "p3d_obfuscator_55/bin/P3DObfuscator55.exe",
        repo_root / "p3d_obfuscator_55/bin/P3DObfuscator.exe",
        Path.cwd() / "p3d_obfuscator_55/bin/P3DObfuscator55.exe",
        Path.cwd() / "p3d_obfuscator_55/bin/P3DObfuscator.exe",
        Path("P:/Tools/P3DObfuscator.exe"),
        Path("P:/Tools/P3DObfuscator55.exe"),
    ]
    for path in possible_paths:
        if path.is_file():
            return str(path)
    return ""


def run_dayz_binarize(
    source_dir,
    binarized_output_dir,
    binarize_exe,
    project_root,
    temp_dir,
    max_processes,
    exclude_file,
    log,
    addon_name="",
):
    if os.path.exists(binarized_output_dir):
        shutil.rmtree(binarized_output_dir)
    os.makedirs(binarized_output_dir, exist_ok=True)

    binpath = str(Path(binarize_exe).parent)
    source_name = addon_name or os.path.basename(os.path.normpath(source_dir)) or "addon"
    texture_temp_dir = os.path.join(temp_dir, "addons", get_safe_temp_name(source_name), "textures")
    if os.path.isdir(texture_temp_dir):
        shutil.rmtree(texture_temp_dir)
    os.makedirs(texture_temp_dir, exist_ok=True)

    isolated_root = ""
    try:
        isolated_root, isolated_source = create_isolated_binarize_source(
            source_dir, temp_dir, source_name, project_root, log
        )
        isolated_project_root_arg = normalize_project_root_arg(isolated_root)
        isolated_working_dir = normalize_working_dir(isolated_root)
        isolated_cmd = [
            binarize_exe,
            "-targetBonesInterval=56",
            f"-maxProcesses={max_processes}",
            "-always",
            "-silent",
            f"-addon={isolated_project_root_arg}",
            f"-textures={texture_temp_dir}",
            f"-binpath={binpath}",
        ]
        if exclude_file:
            isolated_cmd.append(f"-exclude={exclude_file}")
        isolated_cmd.extend([isolated_source, binarized_output_dir])

        log("")
        log("Binarizing P3D files in dependency-isolated mode:")
        log(f"  Original:     {source_dir}")
        log(f"  Source:       {isolated_source}")
        log(f"  Output:       {binarized_output_dir}")
        log(f"  Project root: {isolated_project_root_arg}")
        log(f"  Texture temp: {texture_temp_dir}")
        log("")

        isolated_result = run_logged_subprocess(isolated_cmd, isolated_working_dir, log)
        if isolated_result.returncode != 0:
            raise BuildError(f"Binarize failed with exit code {isolated_result.returncode}: {source_dir}")
        log("Dependency-isolated Binarize completed successfully.")
    finally:
        if isolated_root and os.path.isdir(isolated_root):
            try:
                remove_isolated_binarize_project(isolated_root, log)
            except Exception as e:
                log(f"WARNING: Could not clean isolated Binarize project root: {isolated_root} ({e})")


def run_dayz_texheaders(
    source_dir, binarize_exe, project_root, temp_dir, max_processes, exclude_file, log, addon_name=""
):
    if not os.path.isdir(source_dir):
        raise BuildError(f"Texture header source folder does not exist: {source_dir}")
    if not binarize_exe or not os.path.isfile(binarize_exe):
        raise BuildError("binarize.exe not found. Select the DayZ Tools binarize.exe path.")

    if not has_paa_files(source_dir):
        existing_texheaders = os.path.join(source_dir, "texHeaders.bin")
        if os.path.isfile(existing_texheaders):
            os.remove(existing_texheaders)
            log(f"Removed stale texHeaders.bin because no .paa files are present: {existing_texheaders}")
        log("No .paa files found. Skipping texture headers generation.")
        return ""

    source_name = addon_name or os.path.basename(os.path.normpath(source_dir)) or "addon"
    texheaders_output_dir = os.path.join(temp_dir, "addons", get_safe_temp_name(source_name), "texheaders")
    if os.path.isdir(texheaders_output_dir):
        shutil.rmtree(texheaders_output_dir)
    os.makedirs(texheaders_output_dir, exist_ok=True)

    working_dir = normalize_working_dir(project_root)
    cmd = [
        binarize_exe,
        "-texheaders",
        f"-maxProcesses={max_processes}",
        "-silent",
    ]
    if exclude_file:
        cmd.append(f"-exclude={exclude_file}")
    cmd.extend([source_dir, texheaders_output_dir])

    log("")
    log("Generating texture headers:")
    log(f"  Source: {source_dir}")
    log(f"  Output: {texheaders_output_dir}")
    log("")

    result = subprocess.run(
        cmd,
        cwd=working_dir if os.path.isdir(working_dir) else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=get_subprocess_creationflags(),
        startupinfo=get_hidden_startupinfo(),
    )
    if result.stdout:
        for line in result.stdout.splitlines():
            log(line)

    generated_texheaders = os.path.join(texheaders_output_dir, "texHeaders.bin")
    if result.returncode != 0:
        raise BuildError(f"Texture headers generation failed with exit code {result.returncode}: {source_dir}")
    if not os.path.isfile(generated_texheaders):
        raise BuildError(f"Binarize finished but texHeaders.bin was not created: {source_dir}")

    target_texheaders = os.path.join(source_dir, "texHeaders.bin")
    shutil.copy2(generated_texheaders, target_texheaders)
    if not os.path.isfile(target_texheaders):
        raise BuildError(f"Could not copy texHeaders.bin into pack source: {target_texheaders}")

    log(f"Generated texture headers: {target_texheaders}")
    return target_texheaders


def collect_non_binarized_p3ds(source_dir, extra_patterns=None):
    result = []
    if not os.path.isdir(source_dir):
        return result

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if not file.lower().endswith(".p3d"):
                continue
            if should_skip_file(file, extra_patterns):
                continue

            p3d_path = os.path.join(root, file)
            if is_binarized_p3d(p3d_path):
                continue

            rel_path = os.path.relpath(p3d_path, source_dir).replace(os.sep, WIN_SEP)
            magic = get_p3d_magic(p3d_path)
            result.append((p3d_path, rel_path, magic))

    return result


def collect_binarized_p3ds(source_dir, extra_patterns=None):
    result = []
    if not os.path.isdir(source_dir):
        return result

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if not file.lower().endswith(".p3d"):
                continue
            if should_skip_file(file, extra_patterns):
                continue

            p3d_path = os.path.join(root, file)
            if is_binarized_p3d(p3d_path):
                result.append(p3d_path)

    result.sort(key=lambda path: os.path.relpath(path, source_dir).lower())
    return result


def run_p3d_obfuscator_for_staging(staging_dir, p3d_obfuscator_exe, log, extra_patterns=None):
    if not os.path.isdir(staging_dir):
        raise BuildError(f"Staging folder does not exist: {staging_dir}")
    if not p3d_obfuscator_exe or not os.path.isfile(p3d_obfuscator_exe):
        raise BuildError("P3DObfuscator.exe not found. Select the P3DObfuscator.exe path.")

    p3d_files = collect_binarized_p3ds(staging_dir, extra_patterns)
    if not p3d_files:
        log("No included ODOL P3D files found. Skipping P3D protection.")
        return 0

    log("")
    log(f"Protecting {len(p3d_files)} ODOL P3D file(s):")
    protected = 0
    for p3d_path in p3d_files:
        rel_path = os.path.relpath(p3d_path, staging_dir).replace(os.sep, WIN_SEP)
        temp_output = p3d_path + ".pbo_builder_obfuscated.p3d"
        if os.path.isfile(temp_output):
            os.remove(temp_output)

        log(f"Protecting P3D: {rel_path}")
        result = run_logged_subprocess(
            [p3d_obfuscator_exe, "/Y", p3d_path, temp_output],
            os.path.dirname(p3d_path),
            log,
        )
        if result.returncode != 0 or not os.path.isfile(temp_output):
            if os.path.isfile(temp_output):
                os.remove(temp_output)
            raise BuildError(f"P3DObfuscator failed with exit code {result.returncode}: {p3d_path}")

        os.replace(temp_output, p3d_path)
        protected += 1

    log(f"P3D protection complete: protected={protected}")
    return protected


def create_binarize_source_without_odol(source_dir, temp_dir, addon_name, log, extra_patterns=None):
    safe_addon = get_safe_temp_name(addon_name or os.path.basename(os.path.normpath(source_dir)) or "addon")
    target_dir = os.path.join(temp_dir, "addons", safe_addon, "binarize_input")
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    copied = 0
    skipped_odol = 0

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        rel_root = os.path.relpath(root, source_dir)
        target_root = target_dir if rel_root == "." else os.path.join(target_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)

        for file in files:
            if should_skip_file(file, extra_patterns):
                continue

            source_file = os.path.join(root, file)
            if file.lower().endswith(".p3d") and is_binarized_p3d(source_file):
                skipped_odol += 1
                continue

            shutil.copy2(source_file, os.path.join(target_root, file))
            copied += 1

    log(f"Prepared Binarize input without already-ODOL P3D files: copied={copied}, skipped_odol={skipped_odol}")
    return target_dir, skipped_odol


def ensure_all_p3ds_binarized_in_staging(
    staging_dir,
    binarize_exe,
    project_root,
    temp_dir,
    max_processes,
    exclude_file,
    log,
    addon_name,
    extra_patterns=None,
):
    remaining = collect_non_binarized_p3ds(staging_dir, extra_patterns)
    if not remaining:
        log("All staged P3D files are binarized (ODOL).")
        return 0

    log("")
    log(f"Found {len(remaining)} staged P3D file(s) that are not ODOL after the main Binarize pass.")
    for _, rel_path, magic in remaining:
        magic_label = magic.decode("ascii", errors="replace") if magic else "empty"
        log(f"  Needs targeted Binarize: {rel_path} ({magic_label})")

    retry_root = os.path.join(temp_dir, "addons", get_safe_temp_name(addon_name), "binarized_retry")
    if os.path.isdir(retry_root):
        shutil.rmtree(retry_root)
    os.makedirs(retry_root, exist_ok=True)

    parent_dirs = []
    seen = set()
    for p3d_path, _, _ in remaining:
        parent_dir = os.path.normpath(os.path.dirname(p3d_path))
        parent_key = parent_dir.lower()
        if parent_key in seen:
            continue
        seen.add(parent_key)
        parent_dirs.append(parent_dir)

    for parent_dir in parent_dirs:
        rel_parent = os.path.relpath(parent_dir, staging_dir)
        retry_output_dir = retry_root if rel_parent == "." else os.path.join(retry_root, rel_parent)
        rel_log = "." if rel_parent == "." else rel_parent.replace(os.sep, WIN_SEP)
        retry_input_dir, skipped_odol = create_binarize_source_without_odol(
            parent_dir,
            temp_dir,
            f"{addon_name}_{get_safe_temp_name(rel_log)}",
            log,
            extra_patterns,
        )
        log("")
        log(f"Running targeted Binarize retry for P3D folder: {rel_log}")
        if skipped_odol:
            log(f"Targeted retry will skip {skipped_odol} already-ODOL P3D file(s).")
        run_dayz_binarize(
            source_dir=retry_input_dir,
            binarized_output_dir=retry_output_dir,
            binarize_exe=binarize_exe,
            project_root=project_root,
            temp_dir=temp_dir,
            max_processes=max_processes,
            exclude_file=exclude_file,
            log=log,
            addon_name=f"{addon_name}_{get_safe_temp_name(rel_log)}",
        )
        log(f"Overlaying targeted Binarize retry output: {rel_log}")
        overlay_tree(retry_output_dir, parent_dir)

    remaining_after_retry = collect_non_binarized_p3ds(staging_dir, extra_patterns)
    if remaining_after_retry:
        lines = []
        for _, rel_path, magic in remaining_after_retry:
            magic_label = magic.decode("ascii", errors="replace") if magic else "empty"
            lines.append(f"{rel_path} ({magic_label})")
        joined = "; ".join(lines[:10])
        if len(lines) > 10:
            joined += f"; ... +{len(lines) - 10} more"
        raise BuildError(
            "Binarize did not convert every P3D to ODOL. "
            f"Refusing to pack source/non-binarized models into release PBO: {joined}"
        )

    log("Targeted Binarize retry completed. All staged P3D files are ODOL.")
    return len(remaining)


def run_cfgconvert_to_bin(staging_dir, cfgconvert_exe, log, extra_patterns=None):
    if not os.path.isdir(staging_dir):
        raise BuildError(f"Staging folder does not exist: {staging_dir}")
    if not cfgconvert_exe or not os.path.isfile(cfgconvert_exe):
        raise BuildError("CfgConvert.exe not found. Select the DayZ Tools CfgConvert.exe path.")

    config_files = []
    for root, dirs, files in os.walk(staging_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if file.lower() == "config.cpp":
                config_files.append(os.path.join(root, file))
    if not config_files:
        log("No included config.cpp found. Skipping CPP to BIN.")
        return
    config_files.sort(key=lambda path: os.path.relpath(path, staging_dir).lower())

    log("")
    log(f"Converting {len(config_files)} config.cpp file(s) to config.bin:")
    for config_cpp in config_files:
        config_dir = os.path.dirname(config_cpp)
        config_bin = os.path.join(config_dir, "config.bin")
        rel_config = os.path.relpath(config_cpp, staging_dir).replace(os.sep, WIN_SEP)
        rel_bin = os.path.relpath(config_bin, staging_dir).replace(os.sep, WIN_SEP)
        if os.path.isfile(config_bin):
            os.remove(config_bin)
        cmd = [cfgconvert_exe, "-bin", "-dst", config_bin, config_cpp]
        log("")
        log(f"Converting: {rel_config} -> {rel_bin}")
        result = subprocess.run(
            cmd,
            cwd=config_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=get_subprocess_creationflags(),
            startupinfo=get_hidden_startupinfo(),
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                log(line)
        if result.returncode != 0 or not os.path.isfile(config_bin):
            raise BuildError(f"CfgConvert failed with exit code {result.returncode}: {config_cpp}")
        os.remove(config_cpp)
        log(f"Removed source config.cpp from staging: {rel_config}")


def file_looks_rapified(file_path):
    try:
        with open(file_path, "rb") as file:
            header = file.read(8)
    except OSError:
        return False
    return b"raP" in header[:4]


def run_cfgconvert_rvmats_to_bin(staging_dir, cfgconvert_exe, log, extra_patterns=None):
    if not os.path.isdir(staging_dir):
        raise BuildError(f"Staging folder does not exist: {staging_dir}")
    if not cfgconvert_exe or not os.path.isfile(cfgconvert_exe):
        raise BuildError("CfgConvert.exe not found. Select the DayZ Tools CfgConvert.exe path.")

    rvmat_files = []
    for root, dirs, files in os.walk(staging_dir):
        dirs[:] = [d for d in dirs if not should_skip_dir(d, extra_patterns)]
        for file in files:
            if file.lower().endswith(".rvmat") and not should_skip_file(file, extra_patterns):
                rvmat_files.append(os.path.join(root, file))
    if not rvmat_files:
        log("No included .rvmat found. Skipping RVMAT rapify.")
        return
    rvmat_files.sort(key=lambda path: os.path.relpath(path, staging_dir).lower())

    log("")
    log(f"Converting {len(rvmat_files)} .rvmat file(s) to binary raP:")
    converted = 0
    already_binary = 0
    for rvmat_path in rvmat_files:
        if file_looks_rapified(rvmat_path):
            already_binary += 1
            continue

        rvmat_dir = os.path.dirname(rvmat_path)
        rel_rvmat = os.path.relpath(rvmat_path, staging_dir).replace(os.sep, WIN_SEP)
        temp_rvmat = rvmat_path + ".raptmp"
        if os.path.isfile(temp_rvmat):
            os.remove(temp_rvmat)
        cmd = [cfgconvert_exe, "-bin", "-dst", temp_rvmat, rvmat_path]
        log(f"Rapifying: {rel_rvmat}")
        result = subprocess.run(
            cmd,
            cwd=rvmat_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=get_subprocess_creationflags(),
            startupinfo=get_hidden_startupinfo(),
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                log(line)
        if result.returncode != 0 or not os.path.isfile(temp_rvmat):
            if os.path.isfile(temp_rvmat):
                os.remove(temp_rvmat)
            raise BuildError(f"CfgConvert failed to rapify .rvmat with exit code {result.returncode}: {rvmat_path}")
        os.replace(temp_rvmat, rvmat_path)
        converted += 1

    log(f"RVMAT rapify complete: converted={converted}, already_binary={already_binary}")
