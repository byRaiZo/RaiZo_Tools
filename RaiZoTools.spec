# -*- mode: python ; coding: utf-8 -*-
"""Сборка PyInstaller. Запускать через tools/build.py — он готовит ресурс
версии; готовая ICO берётся напрямую из assets PBO Builder.

Режим — папка, а не один файл: раздаём мы инсталлятор, и распаковывать себя
во временный каталог при каждом запуске (5-15 секунд на PySide6) незачем.
"""
from PyInstaller.utils.hooks import collect_all

# qfluentwidgets держит свои qss, шрифты и картинки внутри пакета и грузит их
# по путям в рантайме — без collect_all окно поднимется без стилей
qfw_datas, qfw_binaries, qfw_hidden = collect_all("qfluentwidgets")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=qfw_binaries,
    datas=[
        ("data", "data"),      # шаблон serverDZ.cfg, каталог карт, шаблон LBmaster
        ("lang", "lang"),      # ru/en/de
        ("core/pbobuilder/assets", "core/pbobuilder/assets"),
        ("core/shortcut_icons", "core/shortcut_icons"),
        ("LICENSE", "."),      # GPLv3 — обязана ехать вместе с бинарником
        ("THIRD_PARTY_NOTICES.md", "."),
    ] + qfw_datas,
    hiddenimports=qfw_hidden + ["win32com.client", "pythoncom", "pywintypes"],
    hookspath=[],
    runtime_hooks=[],
    # tkinter тянет ~10 МБ и не используется; Qt-модули ниже — тоже
    excludes=[
        "tkinter", "unittest", "pydoc_data",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RaiZoTools",
    debug=False,
    strip=False,
    upx=False,              # UPX ускоряет ложные срабатывания антивирусов
    console=False,          # GUI: консольное окно за спиной не нужно
    icon="core/pbobuilder/assets/icon.ico",
    version="build/version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RaiZo Tools",
)
