"""Установка скачанного обновления поверх работающей программы.

Windows не даёт переписать файлы запущенного приложения, поэтому установка идёт
в два хода. Пока программа жива, распаковываем архив рядом — это долгая часть,
полторы тысячи файлов, и её видно в окне. Затем пишем в temp короткий .cmd:
он дожидается выхода нашего процесса по PID, копирует распакованное поверх
установки и запускает программу заново.

Чего помощник не трогает: config, logs и update внутри папки установки. В
портативном режиме настройки лежат рядом с exe, и копирование «как есть»
стёрло бы человеку всё, что он настроил.

Копируем добавлением (robocopy /E), а не зеркалом (/MIR). Зеркало вычистило бы
файлы, которых в новой версии нет, но ценой права удалять в папке установки —
а ошибка в путях у самообновления означает снесённую установку. Лишний файл от
прошлой версии просто лежит и никому не мешает.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .downloader import safe_member
from .updater import UPDATE_DIR, Release, clear_pending, pending
from .version import is_newer

STAGING = UPDATE_DIR / "staging"
_ATTEMPT = UPDATE_DIR / "attempted.json"

# Папки пользователя внутри установки — в портативном режиме они там и лежат.
KEEP = ("config", "logs", "update")

# Сколько помощник ждёт выхода приложения, прежде чем сдаться: 120 попыток по
# полсекунды. Минуты хватит на любое закрытие; вечно ждать нельзя, иначе при
# зависшем процессе в temp останется бессмертный .cmd.
_WAIT_TRIES = 120


def install_dir() -> Path | None:
    """Папка установки либо None, если работаем из исходников."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def _writable(folder: Path) -> bool:
    """Проверка записью, а не по правам: разрешения Windows складываются из
    списков доступа, наследования и групп, и вычислить итог заранее сложнее,
    чем просто попробовать."""
    try:
        probe = folder / ".kr_qts_write_test"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def preflight(rel: Release | None = None) -> str:
    """Пустая строка — можно ставить; иначе причина отказа для показа человеку."""
    rel = rel or pending()
    if rel is None:
        return "обновление не скачано"
    target = install_dir()
    if target is None:
        return "запущена версия из исходников — обновите её через git"
    if not (UPDATE_DIR / rel.asset_name).is_file():
        return "архив обновления не найден"
    if not _writable(target):
        return f"нет прав на запись в {target} — запустите программу от имени администратора"
    return ""


def mark_attempt(version: str) -> None:
    """Запоминает версию, которую сейчас отдаём помощнику.

    Нужна, чтобы после перезапуска отличить «установилось» от «не установилось»:
    сам помощник доложить не может, его к тому времени уже нет.
    """
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    _ATTEMPT.write_text(json.dumps({"version": version}), encoding="utf-8")


def _attempt() -> dict:
    try:
        data = json.loads(_ATTEMPT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def blocked(version: str) -> bool:
    """Версия, установка которой уже срывалась.

    Требовать её повторно нельзя: обязательная проверка на первом запуске
    превратила бы такую версию в замкнутый круг — требуем обновиться, установка
    не срабатывает, версия прежняя, требуем снова. Программа не запустится
    никогда.
    """
    a = _attempt()
    return bool(a.get("failed")) and a.get("version") == version


def settled() -> bool:
    """Разбирает, чем кончилась установка, начатая до перезапуска.

    Установилось — скачанная версия больше не новее работающей: снимаем отметку
    и убираем архив, который иначе занимал бы под сотню мегабайт.

    Не установилось — версия осталась прежней, хотя помощника мы запускали.
    Причины бывают разные: к релизу приложили архив со старой сборкой, копирование
    не прошло, файлы оказались заняты. Разбираться уже поздно, но повторять
    бессмысленно: помечаем версию как несработавшую, чтобы её не требовали снова.
    """
    rel = pending()
    if rel is None:
        return False
    if not is_newer(rel.version):
        clear_pending()
        _ATTEMPT.unlink(missing_ok=True)
        return True
    if _attempt().get("version") == rel.version:
        clear_pending()
        _ATTEMPT.write_text(json.dumps({"version": rel.version, "failed": True}), encoding="utf-8")
    return False


def _clear(folder: Path) -> None:
    import shutil

    shutil.rmtree(folder, ignore_errors=True)


def _source_root(staging: Path, exe: str) -> Path | None:
    """Где в распакованном лежит сама программа.

    Наш архив собран с папкой внутри (tools/build.make_zip), но полагаться на
    это нельзя — релиз может собрать кто угодно. Ищем exe: рядом с ним и есть
    корень.
    """
    if (staging / exe).is_file():
        return staging
    for child in sorted(staging.iterdir()):
        if child.is_dir() and (child / exe).is_file():
            return child
    return None


class ExtractWorker(QThread):
    """Распаковка архива в staging — долгая часть, поэтому в фоне и с прогрессом."""

    progress = Signal(int, int)  # распаковано файлов, всего
    done = Signal(str)  # путь к корню распакованного
    failed = Signal(str)

    def __init__(self, rel: Release, exe: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rel = rel
        self.exe = exe
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        archive = UPDATE_DIR / self.rel.asset_name
        _clear(STAGING)
        try:
            STAGING.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as z:
                members = [m for m in z.infolist() if not m.is_dir()]
                total = len(members)
                for i, m in enumerate(members, 1):
                    if self._cancel:
                        _clear(STAGING)
                        return
                    # Имена внутри архива задаёт тот, кто собрал релиз. Свой мы
                    # собираем сами, но проверка стоит дёшево, а промах здесь
                    # означает запись куда угодно в пределах прав пользователя.
                    dest = safe_member(m.filename, STAGING)
                    if dest is None:
                        raise RuntimeError(f"недопустимое имя в архиве: {m.filename}")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(m) as src, open(dest, "wb") as out:
                        while chunk := src.read(1 << 20):
                            out.write(chunk)
                    self.progress.emit(i, total)
        except (OSError, zipfile.BadZipFile, RuntimeError) as e:
            _clear(STAGING)
            self.failed.emit(str(e))
            return

        root = _source_root(STAGING, self.exe)
        if root is None:
            _clear(STAGING)
            self.failed.emit(f"в архиве нет {self.exe}")
            return
        self.done.emit(str(root))


# --------------------------------------------------------------- помощник

# Две тонкости, обе проверены опытом на пути со знаком «&» (он допустим и в
# имени пользователя, и в имени папки с играми):
#
#   start снимает кавычки и разбирает путь заново, поэтому полный путь в него
#   передавать нельзя — «C:\\Games\\Mods & Tools\\app.exe» разваливается на две
#   команды. Переходим в папку установки и запускаем по голому имени.
#
#   /IS велит копировать и файлы, которые robocopy счёл одинаковыми. Он
#   сравнивает по размеру и времени с допуском в две секунды, а распакованные
#   файлы получают время распаковки — совпадение маловероятно, но цена ошибки
#   здесь наполовину обновлённая установка, а цена лишнего копирования —
#   несколько секунд.
_SCRIPT = """@echo off
chcp 65001 >nul
title {title}
echo.
echo   {message}
echo.
set N=0
:wait
tasklist /FI "PID eq {pid}" /NH 2>nul | find "{pid}" >nul
if errorlevel 1 goto copy
ping -n 2 127.0.0.1 >nul
set /a N+=1
if %N% LSS {tries} goto wait
echo   {stuck}
pause
goto done

:copy
robocopy "{src}" "{dst}" /E /IS /R:2 /W:1 /NFL /NDL /NJH /NJS /NP{excl}
if errorlevel 8 goto failed
rmdir /s /q "{staging}" 2>nul
cd /d "{dst}"
start "" "{exe}"
goto done

:failed
echo.
echo   {failed}
echo.
pause

:done
(goto) 2>nul & del "%~f0"
"""


def write_helper(
    src: Path,
    dst: Path,
    exe: str,
    *,
    title: str = "RaiZo Tools",
    message: str = "Устанавливается обновление, не закрывайте это окно…",
    stuck: str = "Программа не закрылась. Закройте её и запустите обновление заново.",
    failed: str = "Не удалось скопировать файлы. Обновление не установлено.",
    pid: int | None = None,
) -> Path:
    """Пишет .cmd в отдельную временную папку и возвращает путь к нему.

    exe — имя файла программы, не путь: запускаем его из папки установки, куда
    перед этим переходим. Полный путь в start передавать нельзя, см. ниже.
    """
    # Исключения — пути в ИСТОЧНИКЕ: robocopy сверяет /XD с тем, что обходит,
    # то есть с распакованным архивом, а не с папкой установки. Полные пути, а
    # не голые имена: «config» отсекло бы заодно любую вложенную папку с таким
    # именем где-нибудь в потрохах библиотек.
    # Копируем добавлением, поэтому не тронутое источником в установке и так
    # уцелеет — исключения нужны ровно затем, чтобы заводской config из архива
    # не лёг поверх пользовательского.
    excl = "".join(f' /XD "{src / name}"' for name in KEEP)
    text = _SCRIPT.format(
        title=title,
        message=message,
        stuck=stuck,
        failed=failed,
        pid=pid if pid is not None else os.getpid(),
        tries=_WAIT_TRIES,
        src=src,
        dst=dst,
        exe=exe,
        staging=STAGING,
        excl=excl,
    )
    # Файл прямо в temp, без своей папки: последней командой скрипт удаляет сам
    # себя, а удалить ещё и каталог, из которого запущен, ему уже нечем — папка
    # осталась бы висеть после каждого обновления.
    fd, name = tempfile.mkstemp(prefix="kr_qts_update_", suffix=".cmd")
    os.close(fd)
    script = Path(name)
    # cmd читает файл как текст в текущей кодировке — её задаёт chcp 65001
    # в первой строке, поэтому пишем UTF-8. Перевод строки только CRLF: с LF
    # cmd спотыкается на метках перехода.
    script.write_text(text, encoding="utf-8", newline="\r\n")
    return script


def launch_helper(script: Path) -> None:
    """Запускает помощника отдельным процессом и возвращает управление.

    Окно показываем нарочно: приложение сейчас закроется, копирование займёт
    десяток секунд, и без единого признака жизни это выглядит как падение.

    Внешние кавычки нужны обе. cmd /c снимает первую и последнюю, и одиночная
    пара оставила бы «&» в пути на правах разделителя команд; вторая пара
    доживает до разбора и удерживает путь целиком. Проверено на пути со знаком
    «&» и пробелом: одиночные кавычки рвут команду, двойные — нет.
    """
    subprocess.Popen(
        f'cmd.exe /c ""{script}""', creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=str(script.parent), close_fds=True
    )
