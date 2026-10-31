"""Собирает eucalipt-standalone.html — весь сайт одним файлом.

Фото, логотип и шрифты встраиваются внутрь (base64), поэтому файл
открывается на телефоне и компьютере без папок img/ и fonts/ и без интернета
(кроме карты Яндекса). Запуск из корня репозитория:

    python3 tools/build_standalone.py
"""
import base64
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".woff2": "font/woff2"}


def data_uri(path):
    ext = os.path.splitext(path)[1].lower()
    with open(os.path.join(ROOT, path), "rb") as f:
        return f"data:{MIME[ext]};base64," + base64.b64encode(f.read()).decode()


def main():
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as f:
        html = f.read()

    # Шрифты: подставляем CSS со встроенными woff2
    with open(os.path.join(ROOT, "fonts", "fonts.css"), encoding="utf-8") as f:
        css = f.read()
    css = re.sub(r"url\(([^)]+\.woff2)\)", lambda m: f"url({data_uri('fonts/' + m.group(1))})", css)
    html = html.replace('<link rel="stylesheet" href="fonts/fonts.css">', "<style>\n" + css + "</style>")

    # Фото и логотип
    cache = {}

    def img(m):
        src = m.group(2)
        if src not in cache:
            cache[src] = data_uri(src)
        return m.group(1) + cache[src] + m.group(3)

    html = re.sub(r'(src=")(img/[^"]+)(")', img, html)

    # Всё уже внутри файла — ленивая загрузка не нужна (часть просмотрщиков её не поддерживает)
    html = re.sub(r'<img([^>]*?) loading="lazy"', r"<img\1", html)

    assert 'src="img/' not in html and "fonts/fonts.css" not in html
    out = os.path.join(ROOT, "eucalipt-standalone.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"{out}: {len(cache)} картинок, {os.path.getsize(out) / 1e6:.1f} МБ")


if __name__ == "__main__":
    main()
