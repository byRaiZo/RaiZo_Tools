"""Обязательная проверка версии перед первой настройкой.

Первый запуск — самый хрупкий путь в программе: автопоиск папок DayZ,
определение Steam, первый пресет. Это и код, который чаще всего правится, и код,
который новичок проходит ровно один раз. Споткнуться там на версии трёхмесячной
давности — значит не написать в issues, а удалить программу. Плюс состав
настроек между версиями меняется, и настроить всё на старой, а потом обновиться
— верный способ получить конфиг, которого новая версия не ждёт.

Дальше, когда работа налажена, обновление обязательным уже не будет: вламываться
в чужой рабочий процесс нельзя. Жёстко только здесь, где вложено ноль усилий и
обновление стоит дешевле всего.

Запереть человека эта проверка не может ни при каких обстоятельствах. Требуем
обновиться, только когда точно знаем, что версия новее и её есть чем заменить;
нет сети, GitHub молчит, релиз без архива, установка не удалась — идём дальше
молча. Неудобство от старой версии несравнимо с программой, которая не
запускается вообще.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IndeterminateProgressRing,
    PushButton,
    StrongBodyLabel,
)

from core import updater, updater_apply
from core.i18n import tr
from core.updater import Release
from core.version import APP_NAME
from ui.theme import ThemedDialog
from ui.update_dialog import UpdateDialog

# Сколько ждём ответа GitHub, прежде чем предложить не ждать. Проверка идёт с
# запасом дольше (fetch_latest сам отводит себе 15 секунд), но держать человека
# перед пустым окном дольше восьми — уже издевательство.
_WAIT_MS = 8000

# Проверка может пережить своё окно: человек нажал «Продолжить», а ответ придёт
# позже. Поток нельзя дать собрать сборщику мусора, пока он работает.
_detached: list[updater.CheckWorker] = []


class _CheckDialog(ThemedDialog):
    """Ожидание ответа GitHub с возможностью не дожидаться."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.skipped = False
        self.setWindowTitle(tr("upd.check_title", "Проверка обновлений"))
        self.resize(400, 170)

        layout = QVBoxLayout(self)
        layout.addWidget(StrongBodyLabel(tr("upd.check_head", "Смотрим, нет ли версии новее")))
        note = BodyLabel(
            tr(
                "upd.check_body",
                "Перед первой настройкой стоит обновиться: "
                "настройки, сделанные на старой версии, новая может "
                "не понять.",
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        row = QHBoxLayout()
        ring = IndeterminateProgressRing(self)
        ring.setFixedSize(20, 20)
        ring.setStrokeWidth(3)
        row.addWidget(ring)
        self.hint = CaptionLabel("")
        row.addWidget(self.hint)
        row.addStretch(1)
        # Кнопки сначала нет: обычно ответ приходит за секунду, и мелькнувшая
        # кнопка «Продолжить» только подталкивала бы жать её зря.
        self.b_skip = PushButton(tr("upd.check_skip", "Продолжить"))
        self.b_skip.clicked.connect(self._skip)
        self.b_skip.setVisible(False)
        row.addWidget(self.b_skip)
        layout.addLayout(row)

        QTimer.singleShot(_WAIT_MS, self._offer_skip)

    def _offer_skip(self) -> None:
        self.b_skip.setVisible(True)
        self.hint.setText(tr("upd.check_slow", "GitHub не отвечает"))

    def _skip(self) -> None:
        self.skipped = True
        self.reject()

    def reject(self) -> None:
        """Крестик и Escape — то же самое, что «Продолжить»: держать человека
        в окне проверки насильно незачем, дальше его всё равно спросят."""
        self.skipped = True
        super().reject()


def _tell(parent: QWidget | None, text: str) -> None:
    QMessageBox.information(parent, APP_NAME, text)


def _check(parent: QWidget | None) -> Release | None:
    """Последний релиз либо None, если не дождались или сеть недоступна."""
    dlg = _CheckDialog(parent)
    holder: dict[str, Release | None] = {"rel": None}
    worker = updater.CheckWorker()  # без родителя: может пережить окно
    _detached.append(worker)

    def _got(rel: Release | None) -> None:
        holder["rel"] = rel
        try:
            if not dlg.skipped:
                dlg.accept()
        except RuntimeError:
            pass  # окна уже нет — ответ опоздал

    def _gone() -> None:
        if worker in _detached:
            _detached.remove(worker)

    worker.done.connect(_got)
    worker.finished.connect(_gone)
    worker.start()
    dlg.exec()
    return None if dlg.skipped else holder["rel"]


def _apply(rel: Release, parent: QWidget | None) -> bool:
    """Ставит обновление. True — идти дальше, False — приложение закрывается."""
    from ui import update_install

    err = update_install.install(rel, parent)
    if not err:
        return False  # помощник пошёл работать, мы уходим
    # Установка не удалась — пропускаем вперёд, а не запираем.
    _tell(
        parent, tr("upd.must_failed", "Обновление установить не удалось: {m}\n\nПродолжаем на текущей версии.", m=err)
    )
    return True


def ensure_current(parent: QWidget | None = None) -> bool:
    """True — можно идти к мастеру настройки, False — приложение должно выйти."""
    ready = updater.pending()
    if ready is not None and updater.is_update(ready):
        return _apply(ready, parent)  # скачано в прошлый раз — сразу ставим

    rel = _check(parent)
    if not updater.is_update(rel) or rel is None:
        return True
    if updater_apply.blocked(rel.version):
        # Эту версию мы уже пробовали поставить, и она не встала. Требовать её
        # снова — обречь человека на круг без выхода.
        _tell(
            parent,
            tr(
                "upd.must_stuck",
                "Версию {v} установить не удалось, поэтому продолжаем "
                "на текущей. Обновиться можно позже из главного окна.",
                v=rel.version,
            ),
        )
        return True
    if not rel.downloadable:
        # Требовать нечего: к релизу не приложен архив, поставить его мы не можем.
        _tell(
            parent,
            tr(
                "upd.must_noasset",
                "Вышла версия {v}, но к релизу не приложен файл сборки. "
                "Скачайте её со страницы релиза, когда будет удобно.",
                v=rel.version,
            ),
        )
        return True

    dlg = UpdateDialog(rel, mandatory=True, parent=parent)
    worker = updater.DownloadWorker(rel, dlg)
    worker.progress.connect(dlg.set_progress)
    worker.failed.connect(dlg.set_failed)
    worker.done.connect(lambda _p: dlg.set_ready())
    dlg.download_requested.connect(worker.start)
    go = {"v": False}
    dlg.restart_requested.connect(lambda: go.__setitem__("v", True))
    dlg.exec()
    if worker.isRunning():  # закрыли окно посреди загрузки
        worker.cancel()
        worker.wait()
    if not go["v"]:
        return False  # выбрал «Выйти»
    return _apply(rel, parent)
