import base64
import unittest
from unittest import mock

from lead_finder import websearch

SEARCH_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0"><response><results><grouping>
  <group><doc><url>https://zoon.ru/msk/medical/stomatologiya_ulybka/</url><title>Улыбка — отзывы</title></doc></group>
  <group><doc><url>https://www.ulybka-dent.ru/</url><title><hlword>Улыбка</hlword> — стоматология в Москве</title></doc></group>
</grouping></results></response></yandexsearch>"""

ONLY_DIRECTORIES_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0"><response><results><grouping>
  <group><doc><url>https://2gis.ru/moscow/firm/1</url><title>Улыбка, стоматология</title></doc></group>
  <group><doc><url>https://vk.com/ulybka</url><title>Улыбка | ВКонтакте</title></doc></group>
  <group><doc><url>https://other-clinic.ru/</url><title>Другая клиника</title></doc></group>
</grouping></results></response></yandexsearch>"""

NOTHING_FOUND_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0"><response><error code="15">Искомая комбинация слов нигде не встречается</error></response></yandexsearch>"""


def api_response(xml):
    return mock.Mock(status_code=200, json=lambda: {"rawData": base64.b64encode(xml.encode("utf-8")).decode()})


class WebSearchTest(unittest.TestCase):
    def test_parses_docs_with_highlighted_titles(self):
        docs = websearch.parse_results(SEARCH_XML.encode("utf-8"))
        self.assertEqual(docs[1], {"url": "https://www.ulybka-dent.ru/", "title": "Улыбка — стоматология в Москве"})

    def test_nothing_found_is_empty_result(self):
        self.assertEqual(websearch.parse_results(NOTHING_FOUND_XML.encode("utf-8")), [])

    def test_official_site_is_found_by_title(self):
        docs = websearch.parse_results(SEARCH_XML.encode("utf-8"))
        self.assertEqual(websearch.find_official_site("Стоматология «Улыбка»".replace("Стоматология ", ""), docs),
                         "https://www.ulybka-dent.ru/")

    def test_official_site_is_found_by_transliterated_domain(self):
        docs = [{"url": "https://schastlivyvmeste.ru/", "title": "Клиника"}]
        self.assertEqual(websearch.find_official_site("Счастливы вместе", docs), "https://schastlivyvmeste.ru/")

    def test_directories_and_unrelated_sites_are_not_official(self):
        docs = websearch.parse_results(ONLY_DIRECTORIES_XML.encode("utf-8"))
        self.assertIsNone(websearch.find_official_site("Улыбка", docs))

    def test_search_sends_folder_and_api_key(self):
        with mock.patch("lead_finder.websearch.requests.post", return_value=api_response(SEARCH_XML)) as post:
            websearch.search("Улыбка Москва", "key", "folder")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Api-Key key")
        self.assertEqual(kwargs["json"]["folderId"], "folder")
        self.assertEqual(kwargs["json"]["query"]["queryText"], "Улыбка Москва")

    def test_drop_with_official_site_keeps_companies_without_site(self):
        rows = [{"name": "Улыбка"}, {"name": "Зубы и точка"}]
        responses = {"Улыбка Москва": SEARCH_XML, "Зубы и точка Москва": ONLY_DIRECTORIES_XML}

        def post(url, json, headers, timeout):
            return api_response(responses[json["query"]["queryText"]])

        with mock.patch("lead_finder.websearch.requests.post", side_effect=post):
            kept, dropped, notes = websearch.drop_with_official_site(rows, "Москва", "key", "folder")
        self.assertEqual([r["name"] for r in kept], ["Зубы и точка"])
        self.assertEqual(dropped, 1)
        self.assertEqual(notes, [])

    def test_bad_key_raises_readable_error(self):
        bad = mock.Mock(status_code=401, text='{"message": "Unknown api key"}')
        with mock.patch("lead_finder.websearch.requests.post", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, "Яндекс Поиск, код 401"):
                websearch.drop_with_official_site([{"name": "Улыбка"}], "Москва", "key", "folder")

    def test_partial_failures_keep_rows_and_warn(self):
        rows = [{"name": "Улыбка"}, {"name": "Зубы и точка"}]

        def post(url, json, headers, timeout):
            if json["query"]["queryText"].startswith("Улыбка"):
                return mock.Mock(status_code=429, text="Too many requests")
            return api_response(ONLY_DIRECTORIES_XML)

        with mock.patch("lead_finder.websearch.requests.post", side_effect=post):
            kept, dropped, notes = websearch.drop_with_official_site(rows, "Москва", "key", "folder")
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, 0)
        self.assertIn("429", notes[0])


if __name__ == "__main__":
    unittest.main()
