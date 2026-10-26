"""Собирает организации из 2ГИС или Яндекс Карт и оставляет те, у которых нет сайта.

Пример:
    TWOGIS_API_KEY=... python -m lead_finder.maps --source 2gis \
        --query "стоматология" --city "Казань" --out out/dental.csv
"""
import argparse
import math
import os
import time
from urllib.parse import urlparse

import requests

from .common import write_csv

TWOGIS_URL = "https://catalog.api.2gis.com/3.0/items"
YANDEX_URL = "https://search-maps.yandex.ru/v1/"
SOCIAL_TYPES = {"vkontakte", "instagram", "telegram", "whatsapp", "facebook", "ok", "youtube", "tiktok"}
FIELDS = ["source", "source_id", "name", "category", "address", "phones", "socials"]
# ссылки на соцсети и конструкторы-визитки не считаем сайтом: у таких компаний своего сайта нет
NOT_A_WEBSITE = {
    "vk.com": "vk", "vk.ru": "vk", "instagram.com": "instagram", "t.me": "telegram", "telegram.me": "telegram",
    "wa.me": "whatsapp", "whatsapp.com": "whatsapp", "ok.ru": "ok", "facebook.com": "facebook",
    "taplink.cc": "taplink", "taplink.ws": "taplink", "youtube.com": "youtube", "tiktok.com": "tiktok",
    "dzen.ru": "dzen", "avito.ru": "avito",
}
PAGE_DELAY = 0.5
API_KEY_ENV = {"2gis": "TWOGIS_API_KEY", "yandex": "YANDEX_MAPS_API_KEY"}


def social_name(url):
    host = urlparse(url if "//" in url else "//" + url).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    for domain, name in NOT_A_WEBSITE.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def split_links(urls):
    """Делит ссылки на настоящие сайты и соцсети."""
    websites, socials = [], []
    for url in filter(None, urls):
        (socials if social_name(url) else websites).append(url)
    return websites, socials


def fetch_2gis(query, city, api_key, limit, notes=None):
    page_size = 10  # демо-ключ 2ГИС принимает page_size только от 1 до 10
    page = 1
    while True:
        params = {
            "q": f"{query} {city}",
            "key": api_key,
            "fields": "items.contact_groups,items.address_name,items.rubrics",
            "type": "branch",
            "page": page,
            "page_size": page_size,
        }
        data = requests.get(TWOGIS_URL, params=params, timeout=15).json()
        meta = data.get("meta", {})
        if meta.get("code") == 404:  # 2ГИС отвечает 404, когда по запросу ничего не нашлось
            return
        if meta.get("code") != 200:
            message = f"2ГИС, код {meta.get('code')}: {meta.get('error', {}).get('message', meta)}"
            if page == 1:
                raise RuntimeError(message)
            # демо-ключ ограничивает глубину выдачи — отдаём то, что успели собрать
            if notes is not None:
                notes.append(f"2ГИС остановил выдачу на странице {page}: {message}")
            return
        result = data["result"]
        for item in result.get("items", []):
            yield from_2gis(item)
        pages = math.ceil(result.get("total", 0) / page_size)
        if page >= pages or page * page_size >= limit:
            return
        page += 1
        time.sleep(PAGE_DELAY)


def from_2gis(item):
    contacts = [c for group in item.get("contact_groups", []) for c in group.get("contacts", [])]
    websites, social_links = split_links(c.get("url") or c.get("text", "") for c in contacts if c.get("type") == "website")
    return {
        "source": "2gis",
        "source_id": item.get("id", ""),
        "name": item.get("name", ""),
        "category": ", ".join(r.get("name", "") for r in item.get("rubrics", [])),
        "address": item.get("address_name", ""),
        "phones": [c["value"] for c in contacts if c.get("type") == "phone"],
        "websites": websites,
        "socials": sorted({c["type"] for c in contacts if c.get("type") in SOCIAL_TYPES}) + social_links,
        "has_contacts": bool(contacts),
    }


def fetch_yandex(query, city, api_key, limit, notes=None):
    page_size = 50
    skip = 0
    while True:
        params = {
            "text": f"{query} {city}",
            "type": "biz",
            "lang": "ru_RU",
            "results": page_size,
            "skip": skip,
            "apikey": api_key,
        }
        response = requests.get(YANDEX_URL, params=params, timeout=15)
        if response.status_code != 200:
            # Яндекс отвечает на ошибки обычным текстом, а не JSON
            message = f"Яндекс, код {response.status_code}: {response.text.strip()[:300]}"
            if skip == 0:
                raise RuntimeError(message)
            if notes is not None:
                notes.append(f"Яндекс остановил выдачу после {skip} организаций: {message}")
            return
        data = response.json()
        features = data.get("features", [])
        for feature in features:
            yield from_yandex(feature)
        found = int(
            data.get("properties", {})
            .get("ResponseMetaData", {})
            .get("SearchResponse", {})
            .get("found", 0)
        )
        skip += page_size
        if not features or skip >= found or skip >= limit:
            return
        time.sleep(PAGE_DELAY)


def from_yandex(feature):
    meta = feature.get("properties", {}).get("CompanyMetaData", {})
    websites, social_links = split_links([meta.get("url")])
    return {
        "source": "yandex",
        "source_id": meta.get("id", ""),
        "name": meta.get("name", ""),
        "category": ", ".join(c.get("name", "") for c in meta.get("Categories", [])),
        "address": meta.get("address", ""),
        "phones": [p.get("formatted", "") for p in meta.get("Phones", [])],
        "websites": websites,
        "socials": social_links,
        "has_contacts": bool(meta.get("Phones") or meta.get("url")),
    }


def without_website(orgs, require_phone):
    seen = set()
    for org in orgs:
        key = (org["source"], org["source_id"] or org["name"])
        if key in seen or org["websites"]:
            continue
        if require_phone and not org["phones"]:
            continue
        seen.add(key)
        yield {
            **org,
            "phones": "; ".join(org["phones"]),
            "socials": ", ".join(org["socials"]),
        }


def find_without_website(source, query, city, api_key, limit=500, require_phone=True):
    """Возвращает (организации без сайта, статистика с предупреждениями)."""
    fetch = fetch_2gis if source == "2gis" else fetch_yandex
    notes = []
    orgs = list(fetch(query, city, api_key, limit, notes))
    with_contacts = sum(org["has_contacts"] for org in orgs)
    if orgs and not with_contacts:
        notes.append("Источник не вернул контакты ни у одной организации — возможно, ключ не даёт к ним доступа.")
    stats = {"fetched": len(orgs), "with_contacts": with_contacts, "notes": notes}
    return list(without_website(orgs, require_phone)), stats


def main():
    parser = argparse.ArgumentParser(description="Организации без сайта из 2ГИС или Яндекс Карт")
    parser.add_argument("--source", choices=["2gis", "yandex"], required=True)
    parser.add_argument("--query", required=True, help="категория, например «стоматология»")
    parser.add_argument("--city", required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--allow-no-phone", action="store_true", help="не требовать телефон")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    api_key = os.environ[API_KEY_ENV[args.source]]
    rows, stats = find_without_website(
        args.source, args.query, args.city, api_key, args.limit, require_phone=not args.allow_no_phone
    )
    for note in stats["notes"]:
        print(note)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    write_csv(rows, args.out, FIELDS)
    print(f"Записано {len(rows)} организаций без сайта: {args.out}")


if __name__ == "__main__":
    main()
