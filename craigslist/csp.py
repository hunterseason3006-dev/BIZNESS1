"""Пересчитывает Content-Security-Policy в index.html.

Политика разрешает только встроенные скрипты с известными хешами, поэтому
после любой правки <script> нужно запустить: python3 craigslist/csp.py
"""
import base64, hashlib, pathlib, re

page = pathlib.Path(__file__).with_name("index.html")
html = page.read_text(encoding="utf-8")
hashes = [
    "'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode() + "'"
    for body in re.findall(r"<script>(.*?)</script>", html, re.S)
]
policy = "; ".join([
    "default-src 'none'",
    "script-src " + " ".join(hashes),
    "style-src 'unsafe-inline' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src data:",
    "connect-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "object-src 'none'",
])
html = re.sub(r'(<meta http-equiv="Content-Security-Policy" content=")[^"]*(">)', lambda m: m.group(1) + policy + m.group(2), html, count=1)
page.write_text(html, encoding="utf-8")
print(f"CSP обновлена: {len(hashes)} скрипта")
