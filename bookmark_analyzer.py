#!/usr/bin/env python3
"""
Scrapes X bookmarks, fetches linked articles, summarizes each with Ollama,
then gives an honest analysis of your interests and what to pursue next.

Usage:
    python3 bookmark_analyzer.py

Results are saved to your Obsidian vault when configured,
otherwise to the directory where you run the script.

Dependencies:
    pip install httpx playwright browser-cookie3
    playwright install chromium
"""
import json
import time
import re
import sys
from pathlib import Path
from html.parser import HTMLParser

import httpx

MODEL = "gemma4:e2b"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
CDP_URL = "http://127.0.0.1:9222"

# Path.home() is your user home directory, for example /Users/kirankonathala.
OBSIDIAN_VAULT = Path("/Volumes/Projects/Obsidian Vault")

OUTPUT_DIR = OBSIDIAN_VAULT if OBSIDIAN_VAULT and OBSIDIAN_VAULT.exists() else Path.cwd()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CACHE = OUTPUT_DIR / "bookmarks_cache.json"
COOKIES = OUTPUT_DIR / ".bookmark_analyzer_cookies.json"
OUTPUT = OUTPUT_DIR / "bookmark_analysis.md"


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


def fetch_article(url: str, max_chars=3000) -> str:
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        p = TextExtractor()
        p.feed(r.text)
        text = " ".join(p.chunks)
        return text[:max_chars]
    except Exception:
        return ""


def resolve_url(url: str) -> str:
    try:
        r = httpx.head(url, timeout=5, follow_redirects=True)
        return str(r.url)
    except Exception:
        return url


# --- Scraping ---

def scrape_bookmarks() -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:\n  pip install playwright && playwright install chromium")
        sys.exit(1)

    bookmarks = []
    seen = set()

    with sync_playwright() as p:
        print(f"Connecting to existing Chrome via CDP: {CDP_URL}")
        print("Start Chrome yourself with remote debugging enabled, logged into X, then run this script.")
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            print("\nCould not connect to Chrome over CDP.")
            print("Launch Chrome with this command first:")
            print('  open -na "Google Chrome" --args --remote-debugging-port=9222')
            print("Then open x.com, log in, and run this script again.")
            sys.exit(1)

        if browser.contexts:
            context = browser.contexts[0]
        else:
            print("No Chrome context found after connecting.")
            sys.exit(1)

        page = context.new_page()
        page.goto("https://x.com/i/bookmarks")
        try:
            page.wait_for_selector('[data-testid="tweet"]', timeout=15000)
        except Exception:
            print("\nX bookmarks did not load yet.")
            print("Log into X in your existing Chrome window, then press Enter here to continue.")
            input()
            page.goto("https://x.com/i/bookmarks")
            page.wait_for_selector('[data-testid="tweet"]', timeout=120000)

        no_new = 0
        while no_new < 5:
            tweet_els = page.query_selector_all('[data-testid="tweet"]')
            new = 0

            for el in tweet_els:
                try:
                    link = el.query_selector('a[href*="/status/"]')
                    if not link:
                        continue
                    m = re.search(r'/status/(\d+)', link.get_attribute("href") or "")
                    if not m:
                        continue
                    tid = m.group(1)
                    if tid in seen:
                        continue
                    seen.add(tid)
                    new += 1

                    text_el = el.query_selector('[data-testid="tweetText"]')
                    text = text_el.inner_text() if text_el else ""

                    name_el = el.query_selector('[data-testid="User-Name"]')
                    author = (name_el.inner_text().split("\n")[0] if name_el else "").strip()

                    urls = []
                    for a in el.query_selector_all("a[href]"):
                        href = a.get_attribute("href") or ""
                        if href.startswith("http") and "x.com" not in href and "twitter.com" not in href:
                            urls.append(href)
                        elif "t.co/" in href and href.startswith("http"):
                            urls.append(href)

                    bookmarks.append({
                        "id": tid,
                        "author": author,
                        "text": text,
                        "tweet_url": f"https://x.com/i/web/status/{tid}",
                        "external_urls": list(set(urls)),
                        "resolved_urls": [],
                        "article_content": "",
                        "juice": "",
                    })
                except Exception:
                    continue

            if new == 0:
                no_new += 1
            else:
                no_new = 0

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2.5)
            print(f"  {len(bookmarks)} bookmarks collected...", end="\r")

        page.close()
        browser.close()

    print(f"\nScraped {len(bookmarks)} bookmarks total.")
    return bookmarks


# --- Enrichment ---

def enrich(bookmarks: list[dict]) -> list[dict]:
    print("\nResolving URLs and fetching articles...")
    for i, b in enumerate(bookmarks):
        if b.get("resolved_urls") or not b["external_urls"]:
            continue
        print(f"  {i+1}/{len(bookmarks)}: @{b['author'][:25]}", end="\r")
        resolved = []
        for url in b["external_urls"]:
            real = resolve_url(url)
            if not any(x in real for x in ["x.com", "twitter.com", "t.co"]):
                resolved.append(real)
        b["resolved_urls"] = resolved
        if resolved:
            b["article_content"] = fetch_article(resolved[0])
    return bookmarks


# --- Ollama calls ---

def ollama_chat(prompt: str, max_tokens: int) -> str:
    try:
        r = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_predict": max_tokens},
            },
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"].strip()
    except httpx.RequestError as exc:
        print(f"Ollama request failed: {exc}")
        print("Make sure Ollama is running locally and the model is available:")
        print(f"  ollama pull {MODEL}")
        sys.exit(1)
    except (KeyError, ValueError) as exc:
        print(f"Unexpected Ollama response: {exc}")
        sys.exit(1)

def get_juice(b: dict) -> str:
    content = b["text"]
    if b.get("article_content"):
        content += f"\n\n[Article]: {b['article_content'][:2000]}"
    return ollama_chat(
        f"In 1-2 sentences, what's the core idea here that would make someone save this?\n\n{content}",
        max_tokens=120,
    )


def summarize_all(bookmarks: list[dict]) -> list[dict]:
    total = len(bookmarks)
    done = sum(1 for b in bookmarks if b.get("juice"))
    print(f"\nSummarizing {total} bookmarks... ({done} already done)")
    for i, b in enumerate(bookmarks):
        if b.get("juice"):
            continue
        print(f"  {i+1}/{total}: @{b['author'][:25]}", end="\r")
        b["juice"] = get_juice(b)
        CACHE.write_text(json.dumps(bookmarks, indent=2))
    return bookmarks


def read_obsidian() -> str:
    if not OBSIDIAN_VAULT or not Path(OBSIDIAN_VAULT).exists():
        return ""
    notes = []
    for f in Path(OBSIDIAN_VAULT).rglob("*.md"):
        try:
            text = f.read_text().strip()
            if len(text) > 80 and "_template" not in f.name:
                notes.append(f"### {f.stem}\n{text[:1500]}")
        except Exception:
            pass
    return "\n\n".join(notes)


def analyze(bookmarks: list[dict], obsidian: str) -> str:
    bookmark_digest = "\n\n".join(
        f"@{b['author']}: {b['juice']}" + (f"\nLink: {b['resolved_urls'][0]}" if b['resolved_urls'] else "")
        for b in bookmarks
    )

    obsidian_section = obsidian if obsidian else "(No Obsidian notes provided.)"

    prompt = f"""You're doing an honest, direct analysis of someone's X bookmarks — things they deliberately saved over time. Your job: tell them what genuinely interests them and what they should pursue next.

Here are all their X bookmarks:

{bookmark_digest}

Their Obsidian notes (if any):
{obsidian_section}

Give them:

1. **Real themes** — 3-5 specific interests you see across these bookmarks. Not "technology" — actual specific things. Be sharp.

2. **Surprises** — anything unexpected or non-obvious about what they're saving.

3. **One clear direction** — based on these interests, what should they build or pursue next? Be direct. One answer. No hedging, no "it depends." If the signal is genuinely ambiguous, say so plainly.

4. **Tensions** — any contradictions in their interests worth being aware of.

Tone: peer-level and honest. Not a cheerleader. Not therapy. You looked at their data and you're telling them what you see."""

    return ollama_chat(prompt, max_tokens=15000)


# --- Main ---

def main():
    if CACHE.exists():
        print(f"Loading cached bookmarks from {CACHE}")
        print("(Delete the cache file to re-scrape from X)")
        bookmarks = json.loads(CACHE.read_text())
    else:
        bookmarks = scrape_bookmarks()
        bookmarks = enrich(bookmarks)
        CACHE.write_text(json.dumps(bookmarks, indent=2))

    bookmarks = summarize_all(bookmarks)
    CACHE.write_text(json.dumps(bookmarks, indent=2))

    obsidian = read_obsidian()
    print("\nRunning interest analysis...")
    analysis = analyze(bookmarks, obsidian)

    out = [
        "# Bookmark Analysis",
        f"_{time.strftime('%Y-%m-%d')} — {len(bookmarks)} bookmarks_\n",
        "## Analysis\n",
        analysis,
        "\n---\n",
        "## All Bookmarks\n",
    ]
    for b in bookmarks:
        out.append(f"**@{b['author']}** — {b['juice']}")
        if b.get("resolved_urls"):
            out.append(f"<{b['resolved_urls'][0]}>")
        out.append(f"> {b['text'][:250]}\n")

    OUTPUT.write_text("\n".join(out))
    print(f"\nWritten to {OUTPUT}\n")
    print("=" * 60)
    print(analysis)


if __name__ == "__main__":
    main()
