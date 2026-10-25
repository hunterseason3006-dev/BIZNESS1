import os
import tempfile
import unittest
import zipfile
from unittest import mock

from lead_finder.egrul import iter_legal_entities, matches
from lead_finder.maps import fetch_2gis, from_2gis, from_yandex, without_website

EGRUL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Файл>
  <СвЮЛ ИНН="1601000001" ОГРН="1021600000001">
    <СвНаимЮЛ НаимЮЛПолн="ООО «Улыбка»"/>
    <СвАдресЮЛ><АдресРФ КодРегион="16" Индекс="420000" Город="Казань" Улица="Баумана" Дом="1"/></СвАдресЮЛ>
    <СвОКВЭД><СвОКВЭДОсн КодОКВЭД="86.23"/><СвОКВЭДДоп КодОКВЭД="96.02"/></СвОКВЭД>
  </СвЮЛ>
  <СвЮЛ ИНН="1601000002" ОГРН="1021600000002">
    <СвНаимЮЛ НаимЮЛПолн="ООО «Закрыта»"/>
    <СвАдресЮЛ><АдресРФ КодРегион="16" Город="Казань"/></СвАдресЮЛ>
    <СвОКВЭД><СвОКВЭДОсн КодОКВЭД="86.23"/></СвОКВЭД>
    <СвПрекрЮЛ/>
  </СвЮЛ>
  <СвЮЛ ИНН="7701000003" ОГРН="1027700000003">
    <СвНаимЮЛ НаимЮЛПолн="ООО «Другая»"/>
    <СвАдресЮЛ><АдресРФ КодРегион="77" Город="Москва"/></СвАдресЮЛ>
    <СвОКВЭД><СвОКВЭДОсн КодОКВЭД="47.11"/></СвОКВЭД>
  </СвЮЛ>
</Файл>
"""

TWOGIS_ITEM = {
    "id": "70000001",
    "name": "Стоматология «Улыбка»",
    "address_name": "ул. Баумана, 1",
    "rubrics": [{"name": "Стоматология"}],
    "contact_groups": [
        {"contacts": [{"type": "phone", "value": "+7 843 000-00-00"}, {"type": "telegram", "value": "@smile"}]},
    ],
}

YANDEX_FEATURE = {
    "properties": {
        "CompanyMetaData": {
            "id": "123",
            "name": "Стоматология",
            "address": "Казань, Баумана, 1",
            "url": "https://smile.example",
            "Phones": [{"type": "phone", "formatted": "+7 843 111-11-11"}],
            "Categories": [{"name": "Стоматология"}],
        }
    }
}


class MapsTest(unittest.TestCase):
    def test_2gis_item_without_website_is_kept_with_socials(self):
        org = from_2gis(TWOGIS_ITEM)
        self.assertEqual(org["phones"], ["+7 843 000-00-00"])
        self.assertEqual(org["websites"], [])
        self.assertEqual(org["socials"], ["telegram"])

    def test_yandex_site_is_detected(self):
        org = from_yandex(YANDEX_FEATURE)
        self.assertEqual(org["websites"], ["https://smile.example"])

    def test_without_website_drops_sites_and_duplicates(self):
        orgs = [from_2gis(TWOGIS_ITEM), from_2gis(TWOGIS_ITEM), from_yandex(YANDEX_FEATURE)]
        rows = list(without_website(orgs, require_phone=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "2gis")
        self.assertEqual(rows[0]["phones"], "+7 843 000-00-00")

    def test_without_website_requires_phone_by_default(self):
        org = from_2gis({**TWOGIS_ITEM, "contact_groups": []})
        self.assertEqual(list(without_website([org], require_phone=True)), [])
        self.assertEqual(len(list(without_website([org], require_phone=False))), 1)

    def test_2gis_not_found_returns_nothing(self):
        response = mock.Mock(json=lambda: {"meta": {"code": 404, "error": {"type": "itemNotFound"}}})
        with mock.patch("lead_finder.maps.requests.get", return_value=response):
            self.assertEqual(list(fetch_2gis("q", "c", "k", 100)), [])

    def test_2gis_bad_key_raises_readable_error(self):
        response = mock.Mock(json=lambda: {"meta": {"code": 403, "error": {"message": "Authorization error, incorrect key."}}})
        with mock.patch("lead_finder.maps.requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "код 403: Authorization error"):
                list(fetch_2gis("q", "c", "k", 100))


class EgrulTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.xml_path = os.path.join(self.dir.name, "egrul.xml")
        with open(self.xml_path, "w", encoding="utf-8") as f:
            f.write(EGRUL_XML)

    def tearDown(self):
        self.dir.cleanup()

    def test_parses_active_entities_and_skips_liquidated(self):
        entities = list(iter_legal_entities(self.xml_path))
        self.assertEqual([e["inn"] for e in entities], ["1601000001", "7701000003"])
        self.assertEqual(entities[0]["name"], "ООО «Улыбка»")
        self.assertEqual(entities[0]["okved"], "86.23")
        self.assertEqual(entities[0]["region"], "16")
        self.assertIn("Казань", entities[0]["address"])

    def test_filters_by_okved_prefix_and_region(self):
        entities = list(iter_legal_entities(self.xml_path))
        kept = [e for e in entities if matches(e, ["86.2"], ["16"])]
        self.assertEqual([e["inn"] for e in kept], ["1601000001"])

    def test_reads_entities_from_zip(self):
        zip_path = os.path.join(self.dir.name, "egrul.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(self.xml_path, arcname="part1.xml")
        self.assertEqual(len(list(iter_legal_entities(zip_path))), 2)


if __name__ == "__main__":
    unittest.main()
