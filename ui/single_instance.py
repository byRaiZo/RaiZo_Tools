"""Одна копия приложения на пользователя.

Вторая копия — источник тихих неприятностей: два менеджера читают одни и те же
настройки и пресеты, каждый пишет их по-своему, и кто записал последним, того и
правда. Хуже с сервером: обе копии считают его своим, и остановка из одной
оставляет вторую с мёртвым процессом на экране.

Опознаём себя не файлом-замком, а именованным каналом: файл после падения
остался бы лежать и запрещал бы запуск навсегда, а канал закрывается вместе с
процессом, каким бы образом тот ни завершился. Заодно по этому же каналу вторая
копия просит первую показаться — иначе человек, дважды щёлкнувший по ярлыку,
решил бы, что программа не запускается.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# Имя канала. С именем пользователя: на общей машине у каждого своя копия, и
# запрещать вторую только потому, что программа открыта у соседа, незачем.
_NAME = "RaiZo_Tools_single_instance"

_WAIT_MS = 300  # столько ждём ответа уже запущенной копии


def _channel(user: str) -> str:
    return f"{_NAME}_{user}" if user else _NAME


def already_running(user: str = "") -> bool:
    """True — копия уже работает; ей отправлена просьба показаться."""
    sock = QLocalSocket()
    sock.connectToServer(_channel(user))
    if not sock.waitForConnected(_WAIT_MS):
        return False
    sock.write(b"show")
    sock.waitForBytesWritten(_WAIT_MS)
    sock.disconnectFromServer()
    return True


def listen(parent: QObject | None = None, user: str = "") -> QLocalServer:
    """Открывает канал этой копии. Возвращённый объект надо держать живым.

    removeServer перед открытием — на случай, если прошлый запуск завершился
    падением и не убрал за собой имя. Проверять, занято ли оно, уже не нужно:
    сюда попадаем, только когда достучаться до живой копии не вышло.
    """
    QLocalServer.removeServer(_channel(user))
    server = QLocalServer(parent)
    server.listen(_channel(user))
    return server
