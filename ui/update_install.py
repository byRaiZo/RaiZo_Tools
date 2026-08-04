"""Установка обновления из окна: распаковка с прогрессом и передача помощнику.

Вынесено отдельно, потому что установка вызывается из двух мест: из главного
окна, когда человек сам решил обновиться, и с первого запуска, где обновление
обязательно (см. ui/first_run_update).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from core import updater_apply
from core.i18n import tr
from core.updater import Release
from core.version import APP_NAME
from ui.update_dialog import InstallDialog


def install(rel: Release, parent: QWidget | None = None) -> str:
    """Готовит установку и запускает помощника.

    Пустая строка в ответе означает, что помощник пошёл работать и приложение
    обязано закрыться — иначе он будет ждать нас до упора, а потом сдастся.
    Непустая — причина, по которой установка не началась; приложение при этом
    продолжает работать как ни в чём не бывало.
    """
    err = updater_apply.preflight(rel)
    if err:
        return err
    target = updater_apply.install_dir()
    if target is None:  # preflight это уже отсёк; здесь — ради типов
        return tr("upd.install_source", "Запущена версия из исходников — обновите её через git.")
    exe = Path(sys.executable).name

    dlg = InstallDialog(rel, parent)
    out = {"err": ""}
    worker = updater_apply.ExtractWorker(rel, exe, dlg)
    worker.progress.connect(dlg.set_progress)

    def _failed(msg: str) -> None:
        out["err"] = msg
        dlg.set_failed(msg)
        # даём прочитать причину, прежде чем окно исчезнет
        QTimer.singleShot(2500, dlg.accept)

    def _done(root: str) -> None:
        try:
            script = updater_apply.write_helper(
                Path(root),
                target,
                exe,
                title=APP_NAME,
                message=tr("upd.helper_msg", "Устанавливается обновление, не закрывайте это окно…"),
                stuck=tr("upd.helper_stuck", "Программа не закрылась. Закройте её и обновитесь заново."),
                failed=tr("upd.helper_failed", "Не удалось скопировать файлы. Обновление не установлено."),
            )
            # Отмечаем до запуска: после него мы живём считанные секунды, и
            # запись уже может не успеть лечь на диск.
            updater_apply.mark_attempt(rel.version)
            updater_apply.launch_helper(script)
        except OSError as e:
            out["err"] = str(e)
        dlg.accept()

    worker.failed.connect(_failed)
    worker.done.connect(_done)
    worker.start()
    dlg.exec()
    worker.wait()
    return out["err"]
