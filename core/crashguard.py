"""Глобальный перехват непредвиденных ошибок.

Без него необработанное исключение в слоте Qt уходит в stderr, которого у
собранного приложения нет: окно просто исчезает, и пользователю нечего
прислать. Здесь ошибка попадает сразу в три места — в файл рядом с
настройками, в stderr (когда запускают из исходников) и в окно с кнопкой
«Скопировать».

Перехватчиков два, потому что sys.excepthook видит только главный поток;
фоновые потоки Python ходят через threading.excepthook. Оба ведут в одну
функцию.

Окно показывается строго из главного потока: виджеты Qt из чужого потока
трогать нельзя. Из фонового сообщение доезжает сигналом.
"""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QObject, Qt, Signal

# Ошибка внутри самого обработчика не должна крутиться по кругу
_in_handler = threading.Lock()
_reported: set[str] = set()  # один и тот же сбой не показываем дважды
_MAX_REPORTED = 200  # чтобы множество не росло бесконечно
_log_dir: Path | None = None
_app_label = "приложение"


class _Bridge(QObject):
    """Мостик в главный поток: сигнал доставляется в очередь GUI-потока."""

    failed = Signal(str, str)  # заголовок, полный текст


_bridge: _Bridge | None = None


def _crash_file(text: str) -> Path | None:
    """Кладёт отчёт рядом с настройками. Без него в собранной версии от
    падения не остаётся вообще ничего.

    В имени есть микросекунды: одна и та же ошибка в таймере повторяется по
    несколько раз в секунду, и посекундного имени не хватало — отчёты
    затирали друг друга.
    """
    if _log_dir is None:
        return None
    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
        path = _log_dir / f"crash_{datetime.now():%Y-%m-%d_%H-%M-%S_%f}.log"
        path.write_text(text, encoding="utf-8")
        return path
    except OSError:
        return None


def _format(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None, where: str) -> tuple[str, str]:
    head = f"{exc_type.__name__}: {exc}"
    body = "".join(traceback.format_exception(exc_type, exc, tb))
    text = f"{_app_label}\n{datetime.now():%Y-%m-%d %H:%M:%S}\nпоток: {where}\n\n{body}"
    return head, text


def _thread_label() -> str:
    """Имя потока, в котором рвануло. sys.excepthook вызывается в нём же,
    так что QThread.run опознаётся правильно, а не как главный."""
    cur = threading.current_thread()
    return "главный" if cur is threading.main_thread() else cur.name


def _report(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None, where: str) -> None:
    # Ctrl+C и штатный выход — не сбои
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc, tb)
        return
    if not _in_handler.acquire(blocking=False):
        return  # упали внутри обработчика — молчим
    try:
        head, text = _format(exc_type, exc, tb, where)
        # ключ по типу и месту, а не по тексту: одна и та же ошибка в таймере
        # повторяется каждую секунду и завалила бы экран окнами
        key = f"{exc_type.__name__}|{traceback.format_tb(tb)[-1] if tb else ''}"
        first = key not in _reported
        if len(_reported) > _MAX_REPORTED:
            _reported.clear()
        _reported.add(key)

        print(text, file=sys.stderr)
        if not first:
            # повтор той же ошибки: в stderr записали, окном и файлом не шумим
            return
        path = _crash_file(text)
        if path:
            text += f"\n\nОтчёт сохранён: {path}"
        if _bridge is not None:
            # QueuedConnection: из фонового потока окно откроется уже в главном
            _bridge.failed.emit(head, text)
    finally:
        _in_handler.release()


def _show(title: str, text: str) -> None:
    """Окно с ошибкой. Зовётся только в главном потоке."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        return  # окон ещё/уже нет — хватит файла и stderr
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("Непредвиденная ошибка")
    box.setText(title)
    box.setInformativeText(
        "Приложение продолжит работу, но это состояние ненадёжно.\nСкопируйте отчёт и пришлите разработчику."
    )
    box.setDetailedText(text)
    copy_btn = box.addButton("Скопировать отчёт", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.setDefaultButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is copy_btn:
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText(text)


def install(app_label: str = "", log_dir: Path | None = None) -> None:
    """Ставит перехватчики. Зовётся один раз, сразу после создания QApplication."""
    global _bridge, _log_dir, _app_label
    if app_label:
        _app_label = app_label
    _log_dir = log_dir
    _bridge = _Bridge()
    _bridge.failed.connect(_show, Qt.ConnectionType.QueuedConnection)

    sys.excepthook = lambda t, e, tb: _report(t, e, tb, _thread_label())
    threading.excepthook = lambda args: _report(
        args.exc_type, args.exc_value or args.exc_type(), args.exc_traceback, getattr(args.thread, "name", "фоновый")
    )
