import io
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

        result_id = html.split("/download/")[1].split('"')[0]
        csv_resp = self.client.get(f"/download/{result_id}")
        self.assertEqual(csv_resp.mimetype, "text/csv")
        self.assertIn("Улыбка", csv_resp.get_data(as_text=True))

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

    def test_unknown_download_is_404(self):
        self.assertEqual(self.client.get("/download/nope").status_code, 404)


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
