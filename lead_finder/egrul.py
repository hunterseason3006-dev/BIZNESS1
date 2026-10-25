"""Фильтрует юрлица из открытых данных ЕГРЮЛ (data.nalog.ru) по основному ОКВЭД и региону.

ИП намеренно не обрабатываются: в реестре у них ФИО, и выгружать их для поиска клиентов не нужно.

Пример:
    python -m lead_finder.egrul --source egrul_xml.zip --okved 86.23 --region 16 --out out/dental_inn.csv
"""
import argparse
import os
import xml.etree.ElementTree as ET
import zipfile

from .common import write_csv

FIELDS = ["inn", "ogrn", "name", "okved", "region", "address"]


def local(tag):
    return tag.rsplit("}", 1)[-1]


def open_xml_streams(path):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".xml"):
                    with zf.open(name) as stream:
                        yield stream
    else:
        with open(path, "rb") as stream:
            yield stream


def iter_legal_entities(path):
    for stream in open_xml_streams(path):
        for _, elem in ET.iterparse(stream, events=("end",)):
            if local(elem.tag) == "СвЮЛ":
                entity = parse_entity(elem)
                if entity:
                    yield entity
                elem.clear()


def parse_entity(elem):
    # СвПрекрЮЛ — сведения о прекращении деятельности: такие компании не нужны
    if any(local(child.tag) == "СвПрекрЮЛ" for child in elem):
        return None

    okved = ""
    name = ""
    address = {}
    for node in elem.iter():
        tag = local(node.tag)
        if tag == "СвОКВЭДОсн" and node.get("КодОКВЭД"):
            okved = node.get("КодОКВЭД")
        elif tag == "СвНаимЮЛ" and not name:
            name = node.get("НаимЮЛПолн", "")
        elif tag == "АдресРФ" and not address:
            address = dict(node.attrib)

    return {
        "inn": elem.get("ИНН", ""),
        "ogrn": elem.get("ОГРН", ""),
        "name": name,
        "okved": okved,
        "region": address.get("КодРегион", ""),
        "address": ", ".join(
            filter(None, [
                address.get("Индекс"),
                address.get("Регион"),
                address.get("Город") or address.get("НаселПункт"),
                address.get("Улица"),
                address.get("Дом"),
                address.get("Корпус"),
                address.get("Кварт"),
            ])
        ),
    }


def matches(entity, okved_prefixes, regions):
    if okved_prefixes and not any(entity["okved"].startswith(p) for p in okved_prefixes):
        return False
    if regions and entity["region"] not in regions:
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Юрлица из ЕГРЮЛ по ОКВЭД и региону")
    parser.add_argument("--source", required=True, help="zip или xml-файл открытых данных ЕГРЮЛ")
    parser.add_argument("--okved", nargs="+", default=[], help="префиксы основного ОКВЭД, например 86.23 96.02")
    parser.add_argument("--region", nargs="+", default=[], help="коды регионов, например 77 16")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rows = [e for e in iter_legal_entities(args.source) if matches(e, args.okved, args.region)]
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    write_csv(rows, args.out, FIELDS)
    print(f"Записано {len(rows)} юрлиц: {args.out}")


if __name__ == "__main__":
    main()
