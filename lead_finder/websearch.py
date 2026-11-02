"""Проверяет через Яндекс Поиск (Yandex Search API в Yandex Cloud), есть ли у компании собственный сайт.

Карты знают не все сайты: поле «сайт» в карточке часто пустое. Поэтому каждую компанию ищем
в Яндексе по названию и городу и отбрасываем, если в выдаче нашёлся её сайт.

Нужны переменные окружения YANDEX_SEARCH_API_KEY (API-ключ сервисного аккаунта с ролью
search-api.webSearch.user) и YANDEX_FOLDER_ID (каталог, в котором создан ключ).
"""
import base64
import os
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from .common import translit
from .maps import NOT_A_WEBSITE, normalize_name

SEARCH_API_URL = "https://searchapi.api.cloud.yandex.net/v2/web/search"
API_KEY_ENV = "YANDEX_SEARCH_API_KEY"
FOLDER_ENV = "YANDEX_FOLDER_ID"
WORKERS = 5
NOTHING_FOUND_CODE = "15"  # «Искомая комбинация слов нигде не встречается»

# справочники, отзовики и маркетплейсы: страница компании там — не её сайт
AGGREGATORS = {
    "yandex.ru", "ya.ru", "2gis.ru", "2gis.com", "google.com", "google.ru", "zoon.ru", "yell.ru", "flamp.ru",
    "otzovik.com", "irecommend.ru", "spravker.ru", "orgpage.ru", "rusprofile.ru", "list-org.com", "checko.ru",
    "sbis.ru", "zachestnyibiznes.ru", "audit-it.ru", "hh.ru", "superjob.ru", "prodoctorov.ru", "napopravku.ru",
    "docdoc.ru", "sberhealth.ru", "medbooking.com", "tripadvisor.ru", "tripadvisor.com", "restoclub.ru",
    "afisha.ru", "kudago.com", "yclients.com", "dikidi.net", "dikidi.ru", "uslugi.yandex.ru", "profi.ru",
    "youdo.com", "pulscen.ru", "tiu.ru", "blizko.ru", "cataloxy.ru", "spr.ru", "yp.ru", "firmsonmap.com",
    "nalog.ru", "nalog.gov.ru", "wikipedia.org", "wildberries.ru", "ozon.ru", "market.yandex.ru",
    "delivery-club.ru", "eda.yandex.ru", "kupikupon.ru", "biglion.ru", "mapcarta.com", "moscow.cataloxy.ru",
}


def is_configured():
    return bool(os.environ.get(API_KEY_ENV, "").strip() and os.environ.get(FOLDER_ENV, "").strip())


def search(query, api_key, folder_id):
    body = {
        "query": {"searchType": "SEARCH_TYPE_RU", "queryText": query},
        "folderId": folder_id,
        "responseFormat": "FORMAT_XML",
        "groupSpec": {"groupMode": "GROUP_MODE_FLAT", "groupsOnPage": "10", "docsInGroup": "1"},
    }
    response = requests.post(
        SEARCH_API_URL, json=body, headers={"Authorization": f"Api-Key {api_key}"}, timeout=20
    )
    if response.status_code != 200:
        raise RuntimeError(f"Яндекс Поиск, код {response.status_code}: {response.text.strip()[:300]}")
    return parse_results(base64.b64decode(response.json()["rawData"]))


def parse_results(xml_bytes):
    root = ET.fromstring(xml_bytes)
    error = root.find(".//error")
    if error is not None:
        if error.get("code") == NOTHING_FOUND_CODE:
            return []
        raise RuntimeError(f"Яндекс Поиск, ошибка {error.get('code')}: {''.join(error.itertext()).strip()}")
    docs = []
    for doc in root.iter("doc"):
        title = doc.find("title")
        docs.append({
            "url": doc.findtext("url", "").strip(),
            "title": "".join(title.itertext()) if title is not None else "",
        })
    return docs


def host_of(url):
    host = urlparse(url if "//" in url else "//" + url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_directory(host):
    return any(host == d or host.endswith("." + d) for d in AGGREGATORS | NOT_A_WEBSITE.keys())


def find_official_site(name, docs):
    """Ищет в выдаче сайт компании: не справочник, и в заголовке или домене есть её название."""
    norm = normalize_name(name)
    if not norm:
        return None
    compact = translit(norm).replace(" ", "")
    for doc in docs:
        host = host_of(doc["url"])
        if not host or is_directory(host):
            continue
        in_title = norm in normalize_name(doc["title"])
        in_domain = len(compact) >= 4 and compact in host.replace("-", "").replace(".", "")
        if in_title or in_domain:
            return doc["url"]
    return None


def drop_with_official_site(rows, city, api_key, folder_id):
    """Возвращает (компании без сайта, сколько отсеяно, предупреждения)."""
    if not rows:
        return rows, 0, []

    def check(row):
        try:
            return find_official_site(row["name"], search(f"{row['name']} {city}", api_key, folder_id)), None
        except (requests.RequestException, RuntimeError, ValueError, ET.ParseError, KeyError) as exc:
            return None, exc

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(check, rows))

    errors = [exc for _, exc in results if exc]
    if len(errors) == len(rows):
        raise RuntimeError(errors[0])

    kept = [row for row, (site, _) in zip(rows, results) if not site]
    notes = []
    if errors:
        notes.append(f"Яндекс Поиск не ответил по {len(errors)} компаниям — они оставлены без проверки: {errors[0]}")
    return kept, len(rows) - len(kept), notes
