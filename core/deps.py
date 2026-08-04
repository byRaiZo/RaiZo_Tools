"""Разрешение зависимостей модов — полный обход графа.

Зависимости бывают двух видов и раньше обрабатывались порознь:

* Steam-моды объявляют их на странице Workshop (RequiredItems) — их читает
  core.steam_api;
* локальным модам их проставляют вручную в приложении (ModInfo.dependencies,
  ключи реестра).

Из-за раздельной обработки цепочка обрывалась на первом же переходе между
видами: у Steam-мода обход уходил только по воркшопу и не видел вручную
заданных связей, а у локального проверялся ровно один уровень. Здесь обход
общий: на каждом моде собираются зависимости обоих видов, найденные в реестре
разворачиваются дальше, пока не кончатся новые.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import steam_api
from .mods import SOURCE_STEAM, ModInfo, ModRegistry, workshop_ids

MAX_DEPTH = 8  # страховка от бесконечного обхода на битых данных


@dataclass
class DepResult:
    """Что нашлось при обходе, кроме самих исходных модов."""

    found: list[ModInfo] = field(default_factory=list)  # есть в реестре
    missing_workshop: list[str] = field(default_factory=list)  # нет, но известен id
    missing_local: list[str] = field(default_factory=list)  # нет, известен только ключ

    @property
    def empty(self) -> bool:
        return not (self.found or self.missing_workshop or self.missing_local)


def mod_key(mod: ModInfo) -> str:
    """Ключ мода в реестре — по нему же отличаем уже посещённые."""
    return mod.folder_name.lower()


def _direct_deps(mod: ModInfo, api_key: str) -> list[tuple[str, str]]:
    """Прямые зависимости мода: [('steam', workshop_id) | ('local', ключ)].

    Оба вида собираются с любого мода: у Steam-мода могут быть вручную
    дописанные связи, а локальный может зависеть от воркшопного.
    """
    out: list[tuple[str, str]] = []
    if mod.source == SOURCE_STEAM and mod.workshop_id:
        try:
            out += [("steam", wid) for wid in steam_api.get_dependencies(mod.workshop_id, api_key)]
        except Exception:  # noqa: BLE001 — сеть не должна ронять обход
            pass
    out += [("local", key) for key in mod.dependencies]
    return out


def resolve(roots: list[ModInfo], registry: ModRegistry, api_key: str = "", max_depth: int = MAX_DEPTH) -> DepResult:
    """Все зависимости roots вглубь, без дублей и без зацикливания.

    Сами roots в результат не попадают. Обход идёт в ширину: сначала прямые
    зависимости всех исходных модов, потом их зависимости и так далее — так
    первым в списке оказывается то, что ближе к запрошенному моду.
    """
    by_workshop = {m.workshop_id: m for m in registry.all() if m.workshop_id}
    remembered = workshop_ids()  # ключ -> id воркшопа по всем виденным модам
    seen_mods = {mod_key(m) for m in roots}
    seen_missing: set[tuple[str, str]] = set()
    res = DepResult()

    frontier = list(roots)
    for _ in range(max_depth):
        nxt: list[ModInfo] = []
        for mod in frontier:
            for kind, ident in _direct_deps(mod, api_key):
                dep = by_workshop.get(ident) if kind == "steam" else registry.mods.get(ident.lower())
                if dep is not None:
                    key = mod_key(dep)
                    if key in seen_mods:
                        continue  # уже видели — в том числе если цикл
                    seen_mods.add(key)
                    res.found.append(dep)
                    nxt.append(dep)
                    continue
                # мода нет в реестре: дальше идти не от чего, просто отмечаем
                if (kind, ident) in seen_missing:
                    continue
                seen_missing.add((kind, ident))
                if kind == "steam":
                    res.missing_workshop.append(ident)
                    continue
                # Ключ вида «@cf» может принадлежать воркшопному моду, от
                # которого отписались: папки нет, зависимость осталась. Если id
                # мы когда-то видели — это не «локальный ненайденный», а именно
                # неподписанный, и человеку нужна ссылка на подписку, а не
                # сообщение «не найден» без единой подсказки, что делать.
                wid = remembered.get(ident.lower())
                if wid:
                    res.missing_workshop.append(wid)
                else:
                    res.missing_local.append(ident)
        if not nxt:
            break
        frontier = nxt
    return res


def filter_connected(res: DepResult, registry: ModRegistry, mods: list[str], server_mods: list[str]) -> DepResult:
    """Убирает из результата уже подключённые к пресету моды.

    Отсутствующие не трогаем: их нет в реестре, подключить нельзя, но сказать
    о них пользователю нужно.
    """
    return DepResult(
        found=[
            m for m in res.found if registry.index_of(m, mods) is None and registry.index_of(m, server_mods) is None
        ],
        missing_workshop=list(res.missing_workshop),
        missing_local=list(res.missing_local),
    )
