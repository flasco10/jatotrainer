"""Read an opted-in mapper's avatar from their public osu! profile."""
import io
import json
import re
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageOps


def _download(url, hosts, limit):
    def allowed(value):
        parsed = urlsplit(value)
        return parsed.scheme == "https" and parsed.netloc in hosts

    if not allowed(url):
        raise ValueError("Unexpected osu! image address")
    with urlopen(Request(url, headers={"User-Agent": "Jatotrainer"}), timeout=4) as response:
        if not allowed(response.geturl()):
            raise ValueError("Unexpected redirect from osu!")
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("osu! response exceeded the size limit")
    return body


class _ProfilePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.user = None

    def handle_starttag(self, tag, attrs):
        if self.user is not None or tag != "div":
            return
        initial = dict(attrs).get("data-initial-data")
        if initial and '"avatar_url"' in initial:
            try:
                data = json.loads(initial)
            except ValueError:
                return
            if isinstance(data, dict) and isinstance(data.get("user"), dict):
                self.user = data["user"]


def _profile_user(html):
    parser = _ProfilePage()
    parser.feed(html.decode("utf-8", errors="replace"))
    if parser.user is not None:
        return parser.user
    legacy = re.search(rb"""<script\b[^>]*\bid=["']json-user["'][^>]*>(.*?)</script>""", html, re.DOTALL)
    return json.loads(legacy[1]) if legacy else None


def mapper_cdtitle(username):
    profile = _download("https://osu.ppy.sh/users/" + quote(username, safe=""), {"osu.ppy.sh"}, 2**22)
    user = _profile_user(profile)
    if not isinstance(user, dict):
        raise ValueError("public osu! profile was not found")
    if str(user.get("username", "")).casefold() != username.casefold():
        raise ValueError("osu! profile name did not match the mapper")
    data = _download(user["avatar_url"], {"a.ppy.sh", "osu.ppy.sh", "assets.ppy.sh"}, 2**22)
    try:
        with Image.open(io.BytesIO(data)) as source:
            if max(source.size) > 4096:
                raise ValueError("osu! avatar dimensions exceeded the size limit")
            thumbnail = ImageOps.contain(source.convert("RGBA"), (64, 64))
    except Image.DecompressionBombError as error:
        raise ValueError("osu! avatar dimensions exceeded the size limit") from error
    out = io.BytesIO()
    thumbnail.save(out, "PNG")
    return out.getvalue()
