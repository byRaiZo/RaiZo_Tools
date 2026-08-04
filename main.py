"""RaiZo Tools — точка входа."""

from __future__ import annotations

import os
import sys

from core import console, crashguard, i18n, pbo_context_menu, updater_apply
from core.migration import migrate_legacy_v2
from core.pbobuilder.cli import is_cli_invocation, run_cli
from core.settings import APP_DIR, Settings
from core.version import APP_NAME, VERSION


def _greet(channel, window) -> None:
    """Пришла вторая копия: разворачиваем окно вместо второго запуска."""
    conn = channel.nextPendingConnection()
    if conn is not None:
        conn.disconnectFromServer()
    window.restore_from_tray()


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0].lower() in {"server", "preset"}:
        from core.preset_cli import is_preset_cli_invocation, run_preset_cli

        assert is_preset_cli_invocation(argv)
        return run_preset_cli(argv)
    if is_cli_invocation(argv):
        return run_cli(argv)

    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import Theme, setTheme, setThemeColor

    from ui import single_instance
    from ui.first_run_update import ensure_current
    from ui.main_window import MainWindow
    from ui.theme import BRAND_ACCENT, outside_icon
    from ui.wizard import FirstRunWizard

    themes = {"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}

    # Консольные DayZ Tools не должны открывать отдельные окна.
    console.hide()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("byRaiZo")
    if "--smoke-test" in sys.argv:
        return 0
    # Сразу после создания QApplication и до всего остального: если упадёт
    # чтение настроек или сборка окна, пользователь увидит причину, а не
    # исчезнувшее окно. У собранной версии stderr некуда выводить.
    crashguard.install(f"{APP_NAME} {VERSION}", APP_DIR / "logs")
    # общая для всех окон: мастер, главное окно и окна логов берут её сами
    app.setWindowIcon(outside_icon())

    # До чтения настроек: вторая копия не должна успеть ничего ни прочитать,
    # ни записать — иначе два менеджера начнут спорить за одни файлы.
    user = os.environ.get("USERNAME", "")
    if single_instance.already_running(user):
        return 0  # первая копия уже показалась, нам делать нечего
    channel = single_instance.listen(app, user)

    migrate_legacy_v2()
    settings = Settings.load()
    pbo_context_menu.refresh_if_installed()
    setTheme(themes.get(settings.theme, Theme.AUTO))
    setThemeColor(BRAND_ACCENT)

    i18n.load(settings.language)

    # Если помощник отработал, мы уже запущены из новых файлов — снимаем
    # отметку и убираем архив, иначе он так и лежал бы сотней мегабайт.
    updater_apply.settled()

    if not settings.first_run_done:
        # До мастера, а не после: настраивать всё на устаревшей версии, чтобы
        # потом обновиться, — верный способ получить конфиг, которого новая
        # версия не ждёт. Запереть эта проверка не может, см. модуль.
        if not ensure_current():
            return 0
        wizard = FirstRunWizard(settings)
        if not wizard.exec():
            return 0  # пользователь закрыл мастер — выходим без сохранения

    window = MainWindow(settings)
    # вторая копия стучится в канал вместо запуска — показываем эту
    channel.newConnection.connect(lambda: _greet(channel, window))
    window.show()
    # после показа: подхват уже работающих клиента и сервера прошлого запуска
    window.adopt_running()
    # проверка версии — после показа окна: сеть не должна задерживать запуск
    window.start_update_check()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
