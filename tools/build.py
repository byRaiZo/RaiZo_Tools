"""Сборка приложения в папку с exe.

    python tools/build.py            обычная сборка
    python tools/build.py --clean    с очисткой кешей PyInstaller

Готовит ресурс версии и запускает PyInstaller:

    core/pbobuilder/assets/icon.ico  готовая иконка окна и exe
    build/version_info.txt  ресурс версии Windows (свойства файла)

Результат — dist/RaiZo Tools/. Пользовательские данные там не лежат:
config и downloads приложение создаёт в %APPDATA%, см. core/settings.
"""

from __future__ import annotations

import subprocess
import sys
import hashlib
import shutil
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
sys.path.insert(0, str(ROOT))

from core.version import APP_NAME, PUBLISHER, VERSION, parse  # noqa: E402


def make_version_info(dst: Path) -> None:
    """Ресурс версии для свойств exe — Windows показывает его в «Подробно»."""
    nums = (parse(VERSION) + (0, 0, 0, 0))[:4]
    dst.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={nums}, prodvers={nums},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', {PUBLISHER!r}),
      StringStruct('FileDescription', {APP_NAME!r}),
      StringStruct('FileVersion', {VERSION!r}),
      StringStruct('InternalName', 'RaiZoTools'),
      StringStruct('LegalCopyright', 'GPLv3'),
      StringStruct('OriginalFilename', 'RaiZoTools.exe'),
      StringStruct('ProductName', {APP_NAME!r}),
      StringStruct('ProductVersion', {VERSION!r}),
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def make_zip(folder: Path) -> Path:
    """Архив сборки — то, что прикладывается к релизу на GitHub.

    Внутри архива папка с именем программы, а не голые файлы: распаковав такой
    архив куда попало, человек получит папку, а не вываленные в текущий каталог
    полторы тысячи файлов.

    Имя без версии в пути внутри — обновление распаковывается поверх установки,
    и версия в именах папок только мешала бы.
    """
    import zipfile

    dst = folder.parent / f"RaiZo_Tools-v{VERSION}-win64.zip"
    dst.unlink(missing_ok=True)
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, f in enumerate(files, 1):
            z.write(f, folder.name + "/" + str(f.relative_to(folder)).replace("\\", "/"))
            if i % 200 == 0:
                print(f"    упаковано {i}/{len(files)}")
    return dst


def main() -> int:
    dist = ROOT / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    BUILD.mkdir(exist_ok=True)
    print(f"{APP_NAME} {VERSION}")
    make_version_info(BUILD / "version_info.txt")
    print("  готовая ICO и ресурс версии подключены")

    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(ROOT / "RaiZoTools.spec")]
    if "--clean" in sys.argv:
        args.insert(3, "--clean")
    print("  PyInstaller…")
    rc = subprocess.run(args, cwd=ROOT).returncode
    if rc:
        return rc
    out = ROOT / "dist" / "RaiZo Tools"
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"\nсобрано: {out}  ({size / 1024 / 1024:.0f} МБ)")

    if "--no-zip" not in sys.argv:
        print("  архив для релиза…")
        z = make_zip(out)
        digest = hashlib.sha256(z.read_bytes()).hexdigest()
        checksum = z.with_suffix(z.suffix + ".sha256")
        checksum.write_text(f"{digest}  {z.name}\n", encoding="ascii")
        print(f"\nготово: {z}  ({z.stat().st_size / 1024 / 1024:.0f} МБ)")
        print(f"SHA-256: {digest}")
        print("  приложите этот файл к релизу на GitHub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
