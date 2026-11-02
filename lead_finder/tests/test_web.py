import io
import json
import unittest
from unittest import mock

from lead_finder import web
from lead_finder.tests.test_parsers import EGRUL_XML

MAPS_ROW = {
    "source": "2gis", "source_id": "1", "name": "Стоматология «Улыбка»", "category": "Стоматология",
    "address": "ул. Баумана, 1", "phones": "+7 843 000-00-00", "socials": "telegram",
}


class WebTest(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def test_index_renders_both_forms(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('action="/maps"', html)
        self.assertIn('action="/egrul"', html)

    def test_maps_search_shows_rows_and_csv_download(self):
        with mock.patch.object(web.maps, "find_without_website", return_value=([MAPS_ROW], {"fetched": 3, "with_contacts": 3, "notes": ["остановлено на странице 6"]})) as find:
            resp = self.client.post("/maps", data={
                "source": "2gis", "query": "стоматология", "city": "Казань", "api_key": "k", "limit": "100",
            })
        html = resp.get_data(as_text=True)
        find.assert_called_once_with("2gis", "стоматология", "Казань", "k", 100, require_phone=True)
        self.assertIn("Найдено: 1", html)
        self.assertIn("из 3 проверенных", html)
        self.assertIn("остановлено на странице 6", html)
        self.assertIn("Улыбка", html)
        self.assertNotIn('value="k"', html)

        self.assertIn('data-filename="2gis_stomatologiya_kazan.csv"', html)
        csv_json = html.split('<script type="application/json" id="csv-data">')[1].split("</script>")[0]
        csv = json.loads(csv_json)
        self.assertTrue(csv.startswith("source,source_id,name"))
        self.assertIn("Улыбка", csv)

    def test_maps_search_requires_api_key(self):
        with mock.patch.dict(web.os.environ, {}, clear=True):
            html = self.client.post("/maps", data={"source": "2gis", "query": "q", "city": "c"}).get_data(as_text=True)
        self.assertIn("Нужен ключ API", html)

    def test_maps_api_error_is_shown(self):
        with mock.patch.object(web.maps, "find_without_website", side_effect=RuntimeError("2GIS: 403")):
            html = self.client.post("/maps", data={
                "source": "2gis", "query": "q", "city": "c", "api_key": "k",
            }).get_data(as_text=True)
        self.assertIn("2GIS: 403", html)

    def test_egrul_upload_filters_entities(self):
        resp = self.client.post("/egrul", data={
            "file": (io.BytesIO(EGRUL_XML.encode("utf-8")), "egrul.xml"),
            "okved": "86.23", "region": "16",
        }, content_type="multipart/form-data")
        html = resp.get_data(as_text=True)
        self.assertIn("Найдено: 1", html)
        self.assertIn("1601000001", html)

    def test_egrul_requires_filter(self):
        resp = self.client.post("/egrul", data={
            "file": (io.BytesIO(EGRUL_XML.encode("utf-8")), "egrul.xml"),
        }, content_type="multipart/form-data")
        self.assertIn("Укажи хотя бы ОКВЭД или регион", resp.get_data(as_text=True))

    def test_get_on_search_urls_redirects_to_form(self):
        for url in ("/maps", "/egrul"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.headers["Location"], "/")


class WebSearchCheckTest(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()
        self.env = mock.patch.dict(web.os.environ, {"YANDEX_SEARCH_API_KEY": "sk", "YANDEX_FOLDER_ID": "f"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def post(self, **extra):
        stats = {"fetched": 2, "with_contacts": 2, "notes": []}
        with mock.patch.object(web.maps, "find_without_website", return_value=([MAPS_ROW, {**MAPS_ROW, "name": "Другая"}], stats)), \
                mock.patch.object(web.websearch, "drop_with_official_site", return_value=([MAPS_ROW], 1, [])) as drop:
            html = self.client.post("/maps", data={
                "source": "yandex", "query": "q", "city": "Москва", "api_key": "k", **extra,
            }).get_data(as_text=True)
        return html, drop

    def test_checkbox_is_on_by_default_when_configured(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('name="check_web" checked', html)

    def test_check_drops_companies_with_found_site(self):
        html, drop = self.post(check_web="on")
        drop.assert_called_once()
        self.assertEqual(drop.call_args.args[1:], ("Москва", "sk", "f"))
        self.assertIn("Найдено: 1", html)
        self.assertIn("у 1 сайт нашёлся в Яндексе", html)

    def test_check_is_skipped_when_unchecked(self):
        html, drop = self.post()
        drop.assert_not_called()
        self.assertIn("Найдено: 2", html)

    def test_checkbox_disabled_without_env(self):
        with mock.patch.dict(web.os.environ, {}, clear=True):
            html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Проверка через Яндекс Поиск выключена", html)


class PasswordTest(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def test_site_is_open_without_password_env(self):
        with mock.patch.dict(web.os.environ, {}, clear=True):
            self.assertEqual(self.client.get("/").status_code, 200)

    def test_site_requires_login_when_password_set(self):
        with mock.patch.dict(web.os.environ, {"SITE_PASSWORD": "secret"}, clear=True):
            self.assertEqual(self.client.get("/").status_code, 401)
            self.assertEqual(self.client.get("/", auth=("admin", "wrong")).status_code, 401)
            self.assertEqual(self.client.get("/", auth=("admin", "secret")).status_code, 200)


if __name__ == "__main__":
    unittest.main()
