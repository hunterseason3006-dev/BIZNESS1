"""Собирает организации из 2ГИС или Яндекс Карт и оставляет те, у которых нет сайта.

Пример:
    TWOGIS_API_KEY=... python -m lead_finder.maps --source 2gis \
        --query "стоматология" --city "Казань" --out out/dental.csv
"""
import argparse
import math
import os
import time

import requests

from .common import write_csv

TWOGIS_URL = "https://catalog.api.2gis.com/3.0/items"
YANDEX_URL = "https://search-maps.yandex.ru/v1/"
SOCIAL_TYPES = {"vkontakte", "instagram", "telegram", "whatsapp", "facebook", "ok", "youtube", "tiktok"}
FIELDS = ["source", "source_id", "name", "category", "address", "phones", "socials"]
PAGE_DELAY = 0.5
API_KEY_ENV = {"2gis": "TWOGIS_API_KEY", "yandex": "YANDEX_MAPS_API_KEY"}


def fetch_2gis(query, city, api_key, limit):
    page_size = 50
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
            message = meta.get("error", {}).get("message", meta)
            raise RuntimeError(f"2ГИС, код {meta.get('code')}: {message}")
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
    return {
        "source": "2gis",
        "source_id": item.get("id", ""),
        "name": item.get("name", ""),
        "category": ", ".join(r.get("name", "") for r in item.get("rubrics", [])),
        "address": item.get("address_name", ""),
        "phones": [c["value"] for c in contacts if c.get("type") == "phone"],
        "websites": [c.get("url") or c.get("text", "") for c in contacts if c.get("type") == "website"],
        "socials": sorted({c["type"] for c in contacts if c.get("type") in SOCIAL_TYPES}),
    }


def fetch_yandex(query, city, api_key, limit):
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
        data = requests.get(YANDEX_URL, params=params, timeout=15).json()
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
    return {
        "source": "yandex",
        "source_id": meta.get("id", ""),
        "name": meta.get("name", ""),
        "category": ", ".join(c.get("name", "") for c in meta.get("Categories", [])),
        "address": meta.get("address", ""),
        "phones": [p.get("formatted", "") for p in meta.get("Phones", [])],
        "websites": [meta["url"]] if meta.get("url") else [],
        "socials": [],
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
    fetch = fetch_2gis if source == "2gis" else fetch_yandex
    return list(without_website(fetch(query, city, api_key, limit), require_phone))


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
    rows = find_without_website(
        args.source, args.query, args.city, api_key, args.limit, require_phone=not args.allow_no_phone
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    write_csv(rows, args.out, FIELDS)
    print(f"Записано {len(rows)} организаций без сайта: {args.out}")


if __name__ == "__main__":
    main()
