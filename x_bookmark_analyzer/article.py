"""Article URL resolution and lightweight content extraction."""
from html.parser import HTMLParser

import httpx

# --- Article extraction ---

class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "aside"}
    INCLUDE = {"p", "h1", "h2", "h3", "li"}

    def __init__(self):
        super().__init__()
        self._depth = 0
        self._in_block = False
        self._buf = []
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._depth += 1
        elif tag in self.INCLUDE and not self._depth:
            self._in_block = True

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._depth = max(0, self._depth - 1)
        elif tag in self.INCLUDE:
            text = "".join(self._buf).strip()
            if text:
                self.chunks.append(text)
            self._buf = []
            self._in_block = False

    def handle_data(self, data):
        if self._in_block and not self._depth:
            self._buf.append(data)


def fetch_article(url: str, max_chars: int = 3000) -> str:
    try:
        r = httpx.get(
            url,
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )
        p = TextExtractor()
        p.feed(r.text)
        return " ".join(p.chunks)[:max_chars]
    except Exception:
        return ""


def resolve_url(url: str) -> str:
    try:
        r = httpx.head(url, timeout=5, follow_redirects=True)
        return str(r.url)
    except Exception:
        return url
