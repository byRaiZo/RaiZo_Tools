"""CLI PBO Builder, совместимый с командами standalone-версии."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from dataclasses import replace
from pathlib import Path

from core import packer, pbo_context_menu
from core.settings import Settings

from .build import build_all
from .constants import DEFAULT_EXCLUDE_PATTERNS, DEFAULT_PROJECT_ROOT
from .errors import BuildError
from .models import BuildConfig
from .system import create_build_log_path, get_default_max_processes
from .targets import detect_addon_targets

CLI_MARKERS = {
    "-h",
    "--help",
    "-pack",
    "--pack-folder",
    "-packfolder",
    "--output-root",
    "--output-server-root",
    "--pbo-name",
    "--project-root",
    "--temp-dir",
    "--exclude-patterns",
    "--binarize-exe",
    "--cfgconvert-exe",
    "--dssignfile-exe",
    "--private-key",
    "--p3d-obfuscator-exe",
    "--max-processes",
    "-binarizep3d",
    "--binarize-p3d",
    "-cpprvmattobin",
    "--cpp-rvmat-to-bin",
    "-forcerebuild",
    "--force-rebuild",
    "-signpbo",
    "--sign-pbo",
    "-protectp3d",
    "--protect-p3d",
    "-preflight",
    "--preflight",
    "--saved-options",
    "--install-pbo-context-menu",
    "--remove-pbo-context-menu",
    "--no-binarize",
    "--no-convert",
    "--no-force-rebuild",
    "--no-sign",
    "--no-protect",
    "--no-preflight",
    "--no-wait",
}


def is_cli_invocation(argv: list[str]) -> bool:
    return any(arg.lower() in CLI_MARKERS for arg in argv)


def clean_arg(value: object) -> str:
    return str(value or "").strip().strip('"')


def derive_output_from_pack_target(target: object) -> tuple[str, str]:
    target_text = os.path.normpath(clean_arg(target))
    if target_text.lower().endswith(".pbo"):
        pbo_name = os.path.splitext(os.path.basename(target_text))[0]
        parent = os.path.dirname(target_text)
        if os.path.basename(parent).lower() == "addons":
            return os.path.dirname(parent), pbo_name
        return parent, pbo_name
    return target_text, ""


def first_value(*values: object) -> str:
    for value in values:
        cleaned = clean_arg(value)
        if cleaned:
            return cleaned
    return ""


def open_cli_console() -> bool:
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32
    if kernel32.GetConsoleWindow():
        return False
    if not kernel32.AllocConsole():
        return False
    kernel32.SetConsoleTitleW("RaiZo Tools — PBO CLI")
    sys.stdin = open("CONIN$", encoding="utf-8", errors="ignore")
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    return True


def wait_for_enter(created_console: bool) -> None:
    if not created_console:
        return
    try:
        input("\nPress Enter to close...")
    except (EOFError, OSError):
        pass


def _boolean_option(value: bool | None, saved_options: bool, saved_value: bool) -> bool:
    if value is not None:
        return value
    return saved_value if saved_options else False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="RaiZo Tools",
        description="Pack DayZ addon folders from command line.",
    )
    parser.add_argument("-pack", nargs=2, metavar=("SOURCE", "OUTPUT"))
    parser.add_argument("--pack-folder", "-packFolder", dest="pack_folder")
    parser.add_argument("--output-root")
    parser.add_argument("--output-server-root")
    parser.add_argument("--pbo-name")
    parser.add_argument("--project-root")
    parser.add_argument("--temp-dir")
    parser.add_argument("--exclude-patterns")
    parser.add_argument("--binarize-exe")
    parser.add_argument("--cfgconvert-exe")
    parser.add_argument("--dssignfile-exe")
    parser.add_argument("--private-key")
    parser.add_argument("--p3d-obfuscator-exe")
    parser.add_argument("--max-processes", type=int)
    parser.add_argument("--saved-options", action="store_true")
    parser.add_argument("--install-pbo-context-menu", action="store_true")
    parser.add_argument("--remove-pbo-context-menu", action="store_true")
    parser.add_argument("--no-wait", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-binarizeP3D", "-binarizep3d", "--binarize-p3d", dest="binarize_p3d", action="store_true")
    parser.add_argument("--no-binarize", dest="binarize_p3d", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument(
        "-cppRvmatToBin",
        "-cpprvmattobin",
        "--cpp-rvmat-to-bin",
        dest="cpp_rvmat_to_bin",
        action="store_true",
    )
    parser.add_argument("--no-convert", dest="cpp_rvmat_to_bin", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("-forceRebuild", "-forcerebuild", "--force-rebuild", dest="force_rebuild", action="store_true")
    parser.add_argument("--no-force-rebuild", dest="force_rebuild", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("-signPBO", "-signpbo", "--sign-pbo", dest="sign_pbos", action="store_true")
    parser.add_argument("--no-sign", dest="sign_pbos", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("-protectP3D", "-protectp3d", "--protect-p3d", dest="protect_p3d", action="store_true")
    parser.add_argument("--no-protect", dest="protect_p3d", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("-preflight", "--preflight", dest="preflight", action="store_true")
    parser.add_argument("--no-preflight", dest="preflight", action="store_false", help=argparse.SUPPRESS)
    parser.set_defaults(
        binarize_p3d=None,
        cpp_rvmat_to_bin=None,
        force_rebuild=None,
        sign_pbos=None,
        protect_p3d=None,
        preflight=None,
    )
    return parser


def build_cli_settings(args: argparse.Namespace, saved_settings: Settings | None = None) -> BuildConfig:
    saved = saved_settings or Settings.load()
    pack_source, pack_output = args.pack if args.pack else ("", "")
    source_root = first_value(args.pack_folder, pack_source)
    if not source_root:
        raise BuildError("Source folder is required. Use -pack SOURCE OUTPUT or --pack-folder SOURCE.")

    derived_output, derived_name = derive_output_from_pack_target(pack_output) if pack_output else ("", "")
    explicit_output = first_value(args.output_root, derived_output)
    output_root = first_value(explicit_output, saved.pbo_last_output_root)
    if not output_root:
        raise BuildError("Output root is required. Use -pack SOURCE OUTPUT or select output in PBO Builder.")
    output_server = first_value(args.output_server_root)
    if not output_server and not explicit_output:
        output_server = first_value(saved.pbo_last_output_server_root)

    output_addons = os.path.join(output_root, "Addons")
    targets = detect_addon_targets(source_root, output_addons)
    selected = tuple(name for name, _path in targets)
    log_path = create_build_log_path()
    config = packer.build_config(
        saved,
        source_root,
        output_root,
        selected,
        output_server_root=output_server or output_root,
        project_root=first_value(args.project_root, saved.pbo_last_project_root, DEFAULT_PROJECT_ROOT),
        pbo_name=first_value(args.pbo_name, derived_name),
        force_rebuild=_boolean_option(
            args.force_rebuild,
            args.saved_options,
            saved.pack_engine == "full",
        ),
        log_file=log_path,
    )
    return replace(
        config,
        temp_dir=first_value(args.temp_dir, saved.pack_temp_dir, Path(output_root) / ".pbo_builder_temp"),
        use_binarize=_boolean_option(args.binarize_p3d, args.saved_options, saved.pack_use_binarize),
        convert_config=_boolean_option(args.cpp_rvmat_to_bin, args.saved_options, saved.pack_convert_config),
        sign_pbos=_boolean_option(args.sign_pbos, args.saved_options, saved.pack_sign_pbos),
        protect_p3d=_boolean_option(args.protect_p3d, args.saved_options, saved.pack_protect_p3d),
        preflight_before_build=_boolean_option(args.preflight, args.saved_options, saved.pack_preflight),
        binarize_exe=first_value(args.binarize_exe, config.binarize_exe),
        cfgconvert_exe=first_value(args.cfgconvert_exe, config.cfgconvert_exe),
        dssignfile_exe=first_value(args.dssignfile_exe, config.dssignfile_exe),
        p3d_obfuscator_exe=first_value(args.p3d_obfuscator_exe, config.p3d_obfuscator_exe),
        private_key=first_value(args.private_key, config.private_key),
        exclude_patterns=first_value(args.exclude_patterns, config.exclude_patterns, DEFAULT_EXCLUDE_PATTERNS),
        max_processes=max(1, min(args.max_processes or config.max_processes or get_default_max_processes(), 64)),
    )


def run_cli(argv: list[str] | None = None) -> int:
    created_console = open_cli_console()
    should_wait = "--no-wait" not in (argv or ())
    parser = build_parser()
    log_file = None
    try:
        args = parser.parse_args(argv)
        if args.install_pbo_context_menu:
            pbo_context_menu.install()
            print("PBO context menu installed for the current user.")
            return 0
        if args.remove_pbo_context_menu:
            pbo_context_menu.remove()
            print("PBO context menu removed.")
            return 0

        config = build_cli_settings(args)
        log_path = Path(config.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("w", encoding="utf-8")

        def log(message: object) -> None:
            print(message)
            if log_file is not None:
                log_file.write(str(message) + "\n")
                log_file.flush()

        def progress(current: int, total: int) -> None:
            log(f"Progress: {current}/{total}")

        log("CLI build started.")
        log(f"Log file: {log_path}")
        build_all(config, log, progress)
        log("CLI build completed.")
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except BuildError as exc:
        message = f"ERROR: {exc}"
        print(message, file=sys.stderr)
        if log_file is not None:
            log_file.write(message + "\n")
            log_file.flush()
        return 1
    except Exception as exc:
        message = f"ERROR: Unexpected CLI failure: {exc}"
        print(message, file=sys.stderr)
        if log_file is not None:
            log_file.write(message + "\n")
            log_file.flush()
        return 1
    finally:
        if log_file is not None:
            log_file.close()
        wait_for_enter(created_console and should_wait)
