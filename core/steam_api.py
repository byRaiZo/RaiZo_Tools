"""Обращения к Steam: зависимости воркшоп-модов, коллекции, SteamID профилей.

Везде один принцип: с ключом Steam Web API — официальный эндпоинт, без ключа —
публичный (xml/страница воркшопа), чтобы приложение работало и без настройки ключа.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

_UA = {"User-Agent": "RaiZoTools (github.com/byRaiZo/RaiZo_Tools)"}


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


_STEAMID64_RE = re.compile(r"^\d{17}$")
_PROFILE_URL_RE = re.compile(r"steamcommunity\.com/profiles/(\d{17})", re.IGNORECASE)
_VANITY_URL_RE = re.compile(r"steamcommunity\.com/id/([^/?#\s]+)", re.IGNORECASE)
# Допустимые символы имени профиля Steam; длина взята с запасом в обе стороны.
_VANITY_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")


def parse_steamid_input(value: str) -> tuple[str, str]:
    """Разбирает ввод пользователя: («id», SteamID64) либо («vanity», имя).

    Понимает готовый SteamID64, ссылку /profiles/<id>, ссылку /id/<имя>
    и голое vanity-имя. ("", "") — распознать не удалось.
    """
    value = value.strip()
    if not value:
        return "", ""
    if _STEAMID64_RE.match(value):
        return "id", value
    m = _PROFILE_URL_RE.search(value)
    if m:
        return "id", m.group(1)
    m = _VANITY_URL_RE.search(value)
    if m:
        return "vanity", m.group(1)
    # Голое имя профиля. Набор символов у Steam ограничен буквами, цифрами,
    # дефисом и подчёркиванием — это единственное, чем имя отличается от
    # случайно вставленного пути, куска команды или обрывка текста.
    #
    # Строка из одних цифр именем не считается: длину, отличную от семнадцати,
    # человек получает, промахнувшись при вводе SteamID, а не набрав имя. Гнать
    # такое в сеть значит ответить «профиль не найден» вместо «цифр не хватает».
    if _VANITY_RE.match(value) and not value.isdigit():
        return "vanity", value
    return "", ""


def _vanity_via_api(vanity: str, api_key: str) -> str:
    """ISteamUser/ResolveVanityURL — официально, но нужен ключ."""
    params = urllib.parse.urlencode({"key": api_key, "vanityurl": vanity})
    data = json.loads(_get(f"https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?{params}"))
    resp = data.get("response", {})
    return str(resp.get("steamid", "")) if resp.get("success") == 1 else ""


def _vanity_via_xml(vanity: str) -> str:
    """?xml=1 у страницы профиля — публично, ключ не нужен."""
    xml = _get(f"https://steamcommunity.com/id/{urllib.parse.quote(vanity)}/?xml=1")
    m = re.search(r"<steamID64>(\d{17})</steamID64>", xml)
    return m.group(1) if m else ""


def _vanity_via_page(vanity: str) -> str:
    """Запасной вариант: steamid в g_rgProfileData на странице профиля."""
    html = _get(f"https://steamcommunity.com/id/{urllib.parse.quote(vanity)}/")
    m = re.search(r'"steamid"\s*:\s*"(\d{17})"', html)
    return m.group(1) if m else ""


def resolve_steamid(value: str, api_key: str = "") -> str:
    """SteamID64 по ссылке на профиль / vanity-имени / готовому ID.

    Пустая строка — не удалось (нет такого профиля, сеть недоступна и т.п.).
    """
    kind, payload = parse_steamid_input(value)
    if kind == "id":
        return payload
    if kind != "vanity":
        return ""
    if api_key:
        try:
            if sid := _vanity_via_api(payload, api_key):
                return sid
        except Exception:  # noqa: BLE001 — неверный ключ/сеть: падаем на публичные способы
            pass
    for fallback in (_vanity_via_xml, _vanity_via_page):
        try:
            if sid := fallback(payload):
                return sid
        except Exception:  # noqa: BLE001
            continue
    return ""


_DETAILS_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
# Ограничение на размер пачки: у эндпоинта свой предел на длину запроса, а
# сотня id — это уже под 2 КБ формы. Сотнями моды и подключают, так что
# бьём с запасом.
_BATCH = 50


def times_updated(workshop_ids: list[str]) -> dict[str, int]:
    """Время последнего обновления сразу для списка модов: {id: unix-время}.

    Эндпоинт принимает пачку (itemcount + publishedfileids[i]), и спрашивать
    по одному незачем: на 14 модах это 5.6 секунды против 0.5, а при
    недоступной сети — N таймаутов подряд вместо одного.

    Публичный эндпоинт, ключ Steam Web API не нужен. Моды, о которых Steam
    промолчал, в ответе просто отсутствуют.
    """
    out: dict[str, int] = {}
    ids = [w for w in workshop_ids if w]
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start : start + _BATCH]
        fields = {"itemcount": str(len(chunk))}
        for i, wid in enumerate(chunk):
            fields[f"publishedfileids[{i}]"] = wid
        req = urllib.request.Request(_DETAILS_URL, data=urllib.parse.urlencode(fields).encode(), headers=_UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode("utf-8", errors="replace"))
        for d in body.get("response", {}).get("publishedfiledetails", []):
            wid = str(d.get("publishedfileid") or "")
            if wid:
                out[wid] = int(d.get("time_updated", 0))
    return out


def get_time_updated(workshop_id: str) -> int:
    """Время обновления одного мода. Для списка есть times_updated —
    он укладывается в один запрос вместо N."""
    return times_updated([workshop_id]).get(workshop_id, 0)


def deps_via_api(workshop_id: str, api_key: str) -> list[str]:
    """Зависимости через официальный API (children). Бросает исключение при сбое."""
    params = urllib.parse.urlencode(
        {
            "key": api_key,
            "includechildren": "true",
            "publishedfileids[0]": workshop_id,
        }
    )
    data = json.loads(_get(f"https://api.steampowered.com/IPublishedFileService/GetDetails/v1/?{params}"))
    details = data.get("response", {}).get("publishedfiledetails", [])
    if not details:
        return []
    return [str(c["publishedfileid"]) for c in details[0].get("children", [])]


def deps_via_page(workshop_id: str) -> list[str]:
    """Зависимости из секции Required Items страницы воркшопа (без ключа)."""
    html = _get(f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}")
    m = re.search(r'id="RequiredItems"(.*?)</div>\s*</div>', html, re.DOTALL)
    if not m:
        return []
    return list(dict.fromkeys(re.findall(r"filedetails/\?id=(\d+)", m.group(1))))


def get_dependencies(workshop_id: str, api_key: str = "") -> list[str]:
    """ID модов, от которых зависит workshop_id. Ключ есть — API, нет — страница."""
    if api_key:
        try:
            return deps_via_api(workshop_id, api_key)
        except Exception:  # noqa: BLE001 — неверный ключ/сеть: падаем на скрейп
            pass
    try:
        return deps_via_page(workshop_id)
    except Exception:  # noqa: BLE001 — сеть недоступна: считаем, что зависимостей нет
        return []


def parse_collection_id(text: str) -> str:
    """Извлекает id коллекции/мода из ссылки Steam Workshop или принимает голый id."""
    text = text.strip()
    if text.isdigit():
        return text
    m = re.search(r"[?&]id=(\d+)", text)
    return m.group(1) if m else ""


def get_collection_children(collection_id: str) -> list[str]:
    """ID модов, входящих в коллекцию Workshop (порядок — как в коллекции).

    ISteamRemoteStorage/GetCollectionDetails — публичный эндпоинт, ключ не нужен.
    """
    data = urllib.parse.urlencode(
        {
            "collectioncount": "1",
            "publishedfileids[0]": collection_id,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/", data=data, headers=_UA
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode("utf-8", errors="replace"))
    details = body.get("response", {}).get("collectiondetails", [])
    if not details or details[0].get("result") != 1:
        return []
    return [str(c["publishedfileid"]) for c in details[0].get("children", [])]


def get_published_file_names(workshop_ids: list[str]) -> dict[str, str]:
    """Названия воркшоп-айтемов по списку id — для отображения недостающих
    модов коллекции (в реестре их нет, названия взять больше неоткуда)."""
    if not workshop_ids:
        return {}
    params = {"itemcount": str(len(workshop_ids))}
    for i, wid in enumerate(workshop_ids):
        params[f"publishedfileids[{i}]"] = wid
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/", data=data, headers=_UA
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode("utf-8", errors="replace"))
    return {
        str(d.get("publishedfileid")): d.get("title", "")
        for d in body.get("response", {}).get("publishedfiledetails", [])
    }


def resolve_dependencies_deep(workshop_id: str, api_key: str = "", max_depth: int = 5) -> list[str]:
    """Рекурсивные зависимости (без дублей и циклов), в порядке обнаружения."""
    seen: dict[str, None] = {}
    frontier = [workshop_id]
    for _ in range(max_depth):
        nxt = []
        for wid in frontier:
            for dep in get_dependencies(wid, api_key):
                if dep not in seen and dep != workshop_id:
                    seen[dep] = None
                    nxt.append(dep)
        if not nxt:
            break
        frontier = nxt
    return list(seen)
