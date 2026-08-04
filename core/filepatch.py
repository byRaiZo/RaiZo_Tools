"""Симлинки папок скриптов с диска P: для filepatching.

Filepatching позволяет подтягивать скрипты без перепаковки PBO — достаточно
перезапустить клиент и сервер. Для этого папка со скриптами мода должна быть
видна внутри каталога игры по тому же пути, что и на диске P:.

Правило: корень P: считается корнем игры/сервера. Для P:\\KR\\kr_data\\scripts
в каждом корне создаётся настоящая папка KR\\kr_data, а последний элемент пути
(scripts) подключается ссылкой. Ссылка ставится только на последнюю папку —
промежуточные каталоги настоящие, иначе в игру утянулось бы всё дерево.

Ссылки ставятся во все указанные корни: клиент и сервер, stable и Experimental.

Используется junction (mklink /J), как и для модов: в отличие от символьной
ссылки он не требует прав администратора или включённого режима разработчика.
Цель junction разрешается до реального пути (P: — это subst, обычно на
D:\\PDrive), поэтому ссылка продолжает работать, даже если диск P: не
подмонтирован. Исходный P:-путь хранится в настройках — по нему «Актуализировать»
каждый раз заново вычисляет цель, так что смена subst чинится синхронизацией.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import junction
from .i18n import tr
from .mods import _is_link
from .settings import CLIENT_EXE, SERVER_EXE, Settings, is_install

P_DRIVE = "P:"


@dataclass
class Report:
    """Итог операции — для показа пользователю одним сообщением."""

    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)  # пропавшие с P: исходники
    failed: list[str] = field(default_factory=list)  # текст ошибок

    @property
    def changed(self) -> bool:
        return bool(self.created or self.removed)


def is_on_p_drive(path: str | Path) -> bool:
    """Лежит ли путь на диске P:. С других дисков привязка не имеет смысла:
    правило «корень P: = корень игры» работает только для него."""
    try:
        return Path(path).drive.upper() == P_DRIVE
    except (OSError, ValueError):
        return False


def rel_parts(p_path: str | Path) -> tuple[str, ...]:
    """Путь относительно корня P: — то, что воссоздаётся в каталоге игры.

    P:\\KR\\kr_data\\scripts -> ('KR', 'kr_data', 'scripts')
    """
    return Path(p_path).parts[1:]


# поле настроек -> файл, по которому опознаётся установка
_ROOT_MARKERS = (
    ("client_stable", CLIENT_EXE),
    ("client_exp", CLIENT_EXE),
    ("server_stable", SERVER_EXE),
    ("server_exp", SERVER_EXE),
)


def _configured_dirs(settings: Settings) -> list[tuple[Path, str]]:
    """Заданные в настройках папки, которые существуют, вместе с ожидаемым exe."""
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for key, exe in _ROOT_MARKERS:
        value = getattr(settings, key, "")
        if not value:
            continue
        p = Path(value)
        if p.is_dir() and p not in seen:
            seen.add(p)
            out.append((p, exe))
    return out


def game_roots(settings: Settings) -> list[Path]:
    """Корни, куда ставим ссылки: клиент и сервер, stable и Exp.

    Проверяется не просто существование папки, а наличие исполняемого файла.
    После удаления игры из Steam папка нередко остаётся — как раз из-за наших
    же ссылок и созданных приложением файлов (serverDZ.cfg, ban.txt, mpmissions):
    Steam не удаляет каталог, в котором есть чужое содержимое. Такой остаток
    установкой не является и корнем считаться не должен.
    """
    return [p for p, exe in _configured_dirs(settings) if is_install(str(p), exe)]


def stale_roots(settings: Settings) -> list[Path]:
    """Папки, которые заданы в настройках, но игрой больше не являются.

    Ссылки оттуда снимаем: пользы от них нет, а папку они держат живой — из-за
    чего она и продолжает выглядеть установленной игрой.
    """
    return [p for p, exe in _configured_dirs(settings) if not is_install(str(p), exe)]


def link_path(root: Path, p_path: str | Path) -> Path:
    """Куда встанет ссылка внутри конкретного корня."""
    return root.joinpath(*rel_parts(p_path))


def _create(link: Path, target: Path) -> tuple[str, str]:
    """Ставит junction. Возвращает (статус, сообщение).

    Статус: created / kept / failed. Настоящую папку на месте ссылки не трогаем
    никогда — там могут быть файлы пользователя.
    """
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return "failed", f"{link.parent}: {e}"

    if _is_link(link):
        try:
            if link.resolve() == target:
                return "kept", ""
        except OSError:
            pass
        try:
            link.rmdir()  # битая или ведущая не туда — пересоздаём
        except OSError as e:
            return "failed", f"{link}: {e}"
    elif link.exists():
        return "failed", tr("filepatch.err_real_dir", "{p}: тут уже есть настоящая папка — она не тронута", p=link)

    err = junction.create(link, target)
    if err:
        return "failed", f"{link}: {err}"
    return "created", ""


def _remove(link: Path, root: Path) -> tuple[str, str]:
    """Снимает ссылку и подчищает опустевшие промежуточные папки.

    Удаляется только сама ссылка — цель на диске P: не затрагивается. Настоящие
    папки не удаляются: rmdir не трогает непустые каталоги, поэтому чужое
    содержимое рядом останется на месте.
    """
    if not _is_link(link):
        if link.exists():
            return "failed", tr("filepatch.err_real_dir", "{p}: тут уже есть настоящая папка — она не тронута", p=link)
        return "absent", ""
    try:
        link.rmdir()
    except OSError as e:
        return "failed", f"{link}: {e}"

    parent = link.parent
    while parent != root and root in parent.parents:
        try:
            parent.rmdir()  # непустую папку rmdir не тронет — так и надо
        except OSError:
            break
        parent = parent.parent
    return "removed", ""


def _do_remove(rep: Report, entry: str, root: Path) -> None:
    link = link_path(root, entry)
    status, msg = _remove(link, root)
    if status == "removed":
        rep.removed.append(str(link))
    elif status == "failed":
        rep.failed.append(msg)


def _do_create(rep: Report, entry: str, root: Path, target: Path) -> None:
    link = link_path(root, entry)
    status, msg = _create(link, target)
    if status == "created":
        rep.created.append(str(link))
    elif status == "kept":
        rep.kept.append(str(link))
    else:
        rep.failed.append(msg)


def sync(settings: Settings) -> Report:
    """Приводит ссылки в порядок во всех корнях.

    Чего не хватает — создаёт; для исчезнувших с диска P: исходников убирает
    ссылки и вычёркивает их из настроек; из папок, которые перестали быть
    установкой игры, ссылки снимает целиком. Настройки сохраняются, если
    что-то изменилось.
    """
    rep = Report()
    roots = game_roots(settings)
    dead = stale_roots(settings)
    alive: list[str] = []
    gone: list[str] = []
    for entry in settings.filepatch_links:
        (alive if Path(entry).is_dir() else gone).append(entry)

    # 1. папка больше не установка игры — снимаем оттуда все наши ссылки,
    #    иначе они остались бы там навсегда: такой корень мы больше не видим
    for entry in settings.filepatch_links:
        for root in dead:
            _do_remove(rep, entry, root)

    # 2. исходник пропал с диска P: — ссылка потеряла смысл
    for entry in gone:
        rep.stale.append(entry)
        for root in roots:
            _do_remove(rep, entry, root)

    # 3. остальное досоздаём там, где игра действительно установлена
    for entry in alive:
        target = Path(entry).resolve()
        for root in roots:
            _do_create(rep, entry, root, target)

    if gone:
        settings.filepatch_links = alive
        settings.save()
    return rep


def add(settings: Settings, p_path: str | Path) -> tuple[Report, str]:
    """Добавляет папку скриптов и раскидывает ссылки. Второй элемент — текст
    ошибки, если путь не подходит (тогда Report пустой)."""
    path = Path(p_path)
    if not is_on_p_drive(path):
        return Report(), tr("filepatch.err_not_p", "Папка должна находиться на диске P:. Выбрано: {p}", p=path)
    if not rel_parts(path):
        return Report(), tr("filepatch.err_root", "Нельзя подключить корень диска P: — укажите папку скриптов мода.")
    if not path.is_dir():
        return Report(), tr("filepatch.err_missing", "Папки не существует: {p}", p=path)

    known = {str(Path(x)).lower() for x in settings.filepatch_links}
    if str(path).lower() in known:
        return Report(), tr("filepatch.err_dup", "Эта папка уже подключена: {p}", p=path)
    if not game_roots(settings):
        return Report(), tr(
            "filepatch.err_no_roots", "Не задан ни один путь к клиенту или серверу — некуда ставить ссылки."
        )

    settings.filepatch_links.append(str(path))
    settings.save()
    return sync(settings), ""


def remove_all(settings: Settings) -> Report:
    """Снимает все наши ссылки и очищает список.

    Трогает только то, что записано в настройках как подключённое этой
    функцией: моды (DayZServer/MODS) и прочее содержимое каталогов не затрагивается.
    """
    rep = Report()
    # чистим и остатки удалённых установок — там наши ссылки тоже лежат
    roots = game_roots(settings) + stale_roots(settings)
    for entry in settings.filepatch_links:
        for root in roots:
            _do_remove(rep, entry, root)
    settings.filepatch_links = []
    settings.save()
    return rep


def status_lines(settings: Settings) -> list[str]:
    """Человекочитаемый список подключённого — для показа в настройках."""
    roots = game_roots(settings)
    lines = []
    for entry in settings.filepatch_links:
        ok = sum(1 for root in roots if _is_link(link_path(root, entry)))
        gone = "" if Path(entry).is_dir() else tr("filepatch.gone", " — папка пропала с P:")
        lines.append(
            tr("filepatch.line", "{p} — ссылок: {ok} из {total}{gone}", p=entry, ok=ok, total=len(roots), gone=gone)
        )
    return lines
