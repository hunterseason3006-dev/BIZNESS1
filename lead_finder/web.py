"""Веб-интерфейс для поиска организаций без сайта и фильтра ЕГРЮЛ.

Запуск:
    python -m lead_finder.web        # http://127.0.0.1:5000

Если задана переменная SITE_PASSWORD, сайт спрашивает логин (SITE_USER, по умолчанию admin) и пароль.
"""
import hmac
import os
import tempfile
import uuid
from collections import OrderedDict
from urllib.parse import quote

import requests
from flask import Flask, Response, abort, render_template, request

from . import egrul, maps
from .common import csv_text

MAX_STORED_RESULTS = 20
COLUMN_LABELS = {
    "source": "Источник", "source_id": "ID", "name": "Название", "category": "Категория",
    "address": "Адрес", "phones": "Телефоны", "socials": "Соцсети",
    "inn": "ИНН", "ogrn": "ОГРН", "okved": "ОКВЭД", "region": "Регион",
}

app = Flask(__name__)
results = OrderedDict()


@app.before_request
def require_password():
    password = os.environ.get("SITE_PASSWORD")
    if not password:
        return None
    auth = request.authorization
    user = os.environ.get("SITE_USER", "admin")
    if (
        auth
        and hmac.compare_digest(auth.username or "", user)
        and hmac.compare_digest(auth.password or "", password)
    ):
        return None
    return Response("Нужен логин и пароль", 401, {"WWW-Authenticate": 'Basic realm="lead_finder", charset="UTF-8"'})


def store_result(filename, rows, fieldnames):
    result_id = uuid.uuid4().hex
    results[result_id] = (filename, csv_text(rows, fieldnames))
    while len(results) > MAX_STORED_RESULTS:
        results.popitem(last=False)
    return result_id


def split_codes(value):
    return [code for code in value.replace(",", " ").split() if code]


def render(**context):
    context.setdefault("tab", "maps")
    context.setdefault("form", {})
    context["labels"] = COLUMN_LABELS
    context["env_keys"] = {source: bool(os.environ.get(env)) for source, env in maps.API_KEY_ENV.items()}
    return render_template("index.html", **context)


@app.get("/")
def index():
    return render()


@app.post("/maps")
def search_maps():
    form = request.form
    source = form.get("source", "2gis")
    query = form.get("query", "").strip()
    city = form.get("city", "").strip()
    api_key = form.get("api_key", "").strip() or os.environ.get(maps.API_KEY_ENV.get(source, ""), "").strip()
    try:
        limit = min(max(int(form.get("limit") or 100), 1), 5000)
    except ValueError:
        limit = 100
    context = {"tab": "maps", "form": {k: v for k, v in form.items() if k != "api_key"}}

    if source not in maps.API_KEY_ENV or not query or not city:
        return render(error="Укажи источник, категорию и город.", **context)
    if not api_key:
        return render(error="Нужен ключ API.", **context)

    try:
        rows, stats = maps.find_without_website(
            source, query, city, api_key, limit, require_phone=not form.get("allow_no_phone")
        )
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        error = f"Ошибка запроса к API: {exc}"
        if "403" in str(exc):
            error += ". Ключ не подошёл: проверь, что он скопирован целиком и активен в кабинете 2ГИС."
        return render(error=error, **context)

    result_id = store_result(f"{source}_{query}_{city}.csv", rows, maps.FIELDS)
    return render(rows=rows, fields=maps.FIELDS, result_id=result_id, stats=stats, **context)


@app.post("/egrul")
def search_egrul():
    form = request.form
    upload = request.files.get("file")
    okved = split_codes(form.get("okved", ""))
    regions = split_codes(form.get("region", ""))
    context = {"tab": "egrul", "form": dict(form)}

    if not upload or not upload.filename:
        return render(error="Загрузи zip или xml с открытыми данными ЕГРЮЛ.", **context)
    if not okved and not regions:
        return render(error="Укажи хотя бы ОКВЭД или регион, иначе выгрузится весь реестр.", **context)

    suffix = ".zip" if upload.filename.lower().endswith(".zip") else ".xml"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "egrul" + suffix)
        upload.save(path)
        try:
            rows = egrul.find_entities(path, okved, regions)
        except Exception as exc:  # битый архив или XML не того формата
            return render(error=f"Не удалось разобрать файл: {exc}", **context)

    result_id = store_result("egrul.csv", rows, egrul.FIELDS)
    return render(rows=rows, fields=egrul.FIELDS, result_id=result_id, **context)


@app.get("/download/<result_id>")
def download(result_id):
    if result_id not in results:
        abort(404)
    filename, text = results[result_id]
    return Response(
        "\ufeff" + text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
