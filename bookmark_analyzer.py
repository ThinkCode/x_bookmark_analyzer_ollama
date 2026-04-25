#!/usr/bin/env python3
"""
Scrapes X bookmarks, enriches and categorizes them with Ollama, then builds
both a markdown analysis and an interactive HTML dashboard.

Usage:
    python3 bookmark_analyzer.py

Outputs are written to your Obsidian vault when configured, otherwise to the
directory where you run the script.
"""
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path

import httpx

MODEL = "gemma4:e2b"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
CDP_URL = "http://127.0.0.1:9222"

# Path.home() is your user home directory, for example /Users/kirankonathala.
OBSIDIAN_VAULT = Path("/Volumes/Projects/Obsidian Vault")

OUTPUT_DIR = OBSIDIAN_VAULT if OBSIDIAN_VAULT and OBSIDIAN_VAULT.exists() else Path.cwd()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CACHE = OUTPUT_DIR / "bookmarks_cache.json"
OUTPUT = OUTPUT_DIR / "bookmark_analysis.md"
HTML_OUTPUT = OUTPUT_DIR / "bookmark_dashboard.html"

TWITTER_EPOCH = 1288834974657


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


# --- Bookmark normalization ---

def get_x_timestamp(status_id: str | int) -> datetime:
    ms_timestamp = (int(status_id) >> 22) + TWITTER_EPOCH
    return datetime.fromtimestamp(ms_timestamp / 1000.0, tz=timezone.utc)


def timestamp_iso(status_id: str | int) -> str:
    return get_x_timestamp(status_id).isoformat()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def ensure_bookmark_defaults(bookmark: dict) -> dict:
    b = dict(bookmark)
    b["id"] = str(b["id"])
    b.setdefault("author", "")
    b.setdefault("text", "")
    b.setdefault("tweet_url", f"https://x.com/i/web/status/{b['id']}")
    b.setdefault("external_urls", [])
    b.setdefault("resolved_urls", [])
    b.setdefault("article_content", "")
    b.setdefault("juice", "")
    b.setdefault("category", "")
    b.setdefault("created_at", timestamp_iso(b["id"]))
    return b


def hydrate_bookmarks(bookmarks: list[dict]) -> list[dict]:
    hydrated = [ensure_bookmark_defaults(b) for b in bookmarks]
    hydrated.sort(key=lambda b: b["created_at"], reverse=True)
    return hydrated


def save_cache(bookmarks: list[dict]) -> None:
    CACHE.write_text(json.dumps(bookmarks, indent=2))


def bookmark_dt(bookmark: dict) -> datetime:
    return datetime.fromisoformat(bookmark["created_at"])


def merge_bookmarks(existing: list[dict], new: list[dict]) -> list[dict]:
    merged = {b["id"]: ensure_bookmark_defaults(b) for b in existing}
    for bookmark in new:
        merged[bookmark["id"]] = ensure_bookmark_defaults(bookmark)
    return sorted(merged.values(), key=lambda b: b["created_at"], reverse=True)


# --- Scraping ---

def scrape_bookmarks(existing_ids: set[str] | None = None, allow_failure: bool = False) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:\n  pip install playwright && playwright install chromium")
        if allow_failure:
            return []
        sys.exit(1)

    existing_ids = existing_ids or set()
    bookmarks = []
    seen = set(existing_ids)

    with sync_playwright() as p:
        print(f"Connecting to existing Chrome via CDP: {CDP_URL}")
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            if allow_failure:
                print("\nCould not connect to Chrome over CDP. Continuing with cached bookmarks only.")
                return []
            print("\nCould not connect to Chrome over CDP.")
            print("Launch Chrome with this command first:")
            print('  open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-playwright-x')
            print("Then open x.com, log in, and run this script again.")
            sys.exit(1)

        if not browser.contexts:
            if allow_failure:
                print("No Chrome context found. Continuing with cached bookmarks only.")
                browser.close()
                return []
            print("No Chrome context found after connecting.")
            sys.exit(1)

        context = browser.contexts[0]
        page = context.new_page()
        page.goto("https://x.com/i/bookmarks")
        try:
            page.wait_for_selector('[data-testid="tweet"]', timeout=15000)
        except Exception:
            if allow_failure:
                print("Bookmarks did not load from Chrome. Continuing with cached bookmarks only.")
                page.close()
                browser.close()
                return []
            print("\nX bookmarks did not load yet.")
            print("Log into X in your Chrome window, then press Enter here to continue.")
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

                    href = link.get_attribute("href") or ""
                    match = re.search(r"/status/(\d+)", href)
                    if not match:
                        continue

                    tid = match.group(1)
                    if tid in seen:
                        continue

                    seen.add(tid)
                    new += 1

                    text_el = el.query_selector('[data-testid="tweetText"]')
                    text = text_el.inner_text() if text_el else ""

                    name_el = el.query_selector('[data-testid="User-Name"]')
                    author = (name_el.inner_text().split("\n")[0] if name_el else "").strip()

                    urls = []
                    for anchor in el.query_selector_all("a[href]"):
                        anchor_href = anchor.get_attribute("href") or ""
                        if anchor_href.startswith("http") and "x.com" not in anchor_href and "twitter.com" not in anchor_href:
                            urls.append(anchor_href)
                        elif "t.co/" in anchor_href and anchor_href.startswith("http"):
                            urls.append(anchor_href)

                    bookmarks.append(
                        {
                            "id": tid,
                            "author": author,
                            "text": text,
                            "tweet_url": f"https://x.com/i/web/status/{tid}",
                            "external_urls": sorted(set(urls)),
                            "resolved_urls": [],
                            "article_content": "",
                            "juice": "",
                            "category": "",
                            "created_at": timestamp_iso(tid),
                        }
                    )
                except Exception:
                    continue

            no_new = no_new + 1 if new == 0 else 0
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2.5)
            print(f"  {len(bookmarks)} new bookmarks collected...", end="\r")

        page.close()
        browser.close()

    print(f"\nScraped {len(bookmarks)} new bookmarks.")
    return bookmarks


# --- Enrichment ---

def enrich(bookmarks: list[dict]) -> list[dict]:
    pending = [b for b in bookmarks if not b.get("resolved_urls") and b.get("external_urls")]
    print(f"\nResolving URLs and fetching articles... ({len(pending)} pending)")
    for i, bookmark in enumerate(bookmarks):
        if bookmark.get("resolved_urls") or not bookmark["external_urls"]:
            continue
        print(f"  {i+1}/{len(bookmarks)}: @{bookmark['author'][:25]}", end="\r")
        resolved = []
        for url in bookmark["external_urls"]:
            real = resolve_url(url)
            if not any(x in real for x in ["x.com", "twitter.com", "t.co"]):
                resolved.append(real)
        bookmark["resolved_urls"] = resolved
        if resolved and not bookmark.get("article_content"):
            bookmark["article_content"] = fetch_article(resolved[0])
        save_cache(bookmarks)
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


def get_juice(bookmark: dict) -> str:
    content = bookmark["text"]
    if bookmark.get("article_content"):
        content += f"\n\n[Article]: {bookmark['article_content'][:2000]}"
    return ollama_chat(
        f"In 1-2 sentences, what's the core idea here that would make someone save this?\n\n{content}",
        max_tokens=120,
    )


def get_category(bookmark: dict) -> str:
    content = clean_text(bookmark.get("juice") or bookmark.get("text") or "")
    article = clean_text(bookmark.get("article_content", ""))[:1000]
    prompt = f"""Assign exactly one category label to this X bookmark.

Rules:
- 2 to 4 words
- title case
- specific, not generic
- no punctuation
- return only the label

Bookmark text:
{content}

Article excerpt:
{article}
"""
    category = ollama_chat(prompt, max_tokens=20).splitlines()[0].strip().strip('"').strip("'")
    category = re.sub(r"[^A-Za-z0-9 /&+-]", "", category).strip() or "Uncategorized"
    return category[:40]


def summarize_all(bookmarks: list[dict]) -> list[dict]:
    pending = sum(1 for b in bookmarks if not b.get("juice"))
    print(f"\nSummarizing {len(bookmarks)} bookmarks... ({pending} pending)")
    for i, bookmark in enumerate(bookmarks):
        if bookmark.get("juice"):
            continue
        print(f"  {i+1}/{len(bookmarks)}: @{bookmark['author'][:25]}", end="\r")
        bookmark["juice"] = get_juice(bookmark)
        save_cache(bookmarks)
    return bookmarks


def categorize_all(bookmarks: list[dict]) -> list[dict]:
    pending = sum(1 for b in bookmarks if not b.get("category"))
    print(f"\nCategorizing {len(bookmarks)} bookmarks... ({pending} pending)")
    for i, bookmark in enumerate(bookmarks):
        if bookmark.get("category"):
            continue
        print(f"  {i+1}/{len(bookmarks)}: @{bookmark['author'][:25]}", end="\r")
        bookmark["category"] = get_category(bookmark)
        save_cache(bookmarks)
    return bookmarks


def read_obsidian() -> str:
    if not OBSIDIAN_VAULT or not Path(OBSIDIAN_VAULT).exists():
        return ""
    notes = []
    for file in Path(OBSIDIAN_VAULT).rglob("*.md"):
        try:
            text = file.read_text().strip()
            if len(text) > 80 and "_template" not in file.name:
                notes.append(f"### {file.stem}\n{text[:1500]}")
        except Exception:
            pass
    return "\n\n".join(notes)


def analyze(bookmarks: list[dict], obsidian: str) -> str:
    bookmark_digest = "\n\n".join(
        f"{b['created_at']} | @{b['author']} | {b['category']}: {b['juice']}"
        + (f"\nLink: {b['resolved_urls'][0]}" if b["resolved_urls"] else "")
        for b in bookmarks[:250]
    )

    obsidian_section = obsidian if obsidian else "(No Obsidian notes provided.)"

    prompt = f"""You're doing an honest, direct analysis of someone's X bookmarks.

Here are their bookmarks, with timestamps, categories, and summaries:

{bookmark_digest}

Their Obsidian notes (if any):
{obsidian_section}

Give them:

1. Real themes - 3 to 5 specific interests you see across these bookmarks.
2. Surprises - anything unexpected or non-obvious about what they're saving.
3. One clear direction - what they should build or pursue next.
4. Tensions - contradictions or tradeoffs in their interests.

Keep it sharp, specific, and peer-level."""

    return ollama_chat(prompt, max_tokens=1800)


# --- Output helpers ---

def month_key(bookmark: dict) -> str:
    return bookmark_dt(bookmark).strftime("%Y-%m")


def year_key(bookmark: dict) -> str:
    return bookmark_dt(bookmark).strftime("%Y")


def short_excerpt(bookmark: dict, length: int = 220) -> str:
    source = clean_text(bookmark.get("text") or bookmark.get("juice") or "")
    if len(source) <= length:
        return source
    return source[: length - 1].rstrip() + "…"


def build_dashboard_data(bookmarks: list[dict]) -> dict:
    sorted_bookmarks = sorted(bookmarks, key=lambda b: b["created_at"], reverse=True)
    month_counts = Counter(month_key(b) for b in sorted_bookmarks)
    year_counts = Counter(year_key(b) for b in sorted_bookmarks)
    category_counts = Counter(b.get("category") or "Uncategorized" for b in sorted_bookmarks)

    month_labels = sorted(month_counts)
    month_series = [{"month": label, "count": month_counts[label]} for label in month_labels]

    years = sorted(year_counts)
    heatmap = []
    for year in years:
        row = {"year": year, "months": []}
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            row["months"].append({"month": month, "count": month_counts.get(key, 0), "key": key})
        heatmap.append(row)

    categories = []
    for category, count in category_counts.most_common():
        categories.append(
            {
                "name": category,
                "count": count,
                "bookmarks": [
                    {
                        "id": b["id"],
                        "author": b["author"],
                        "tweet_url": b["tweet_url"],
                        "resolved_url": b["resolved_urls"][0] if b["resolved_urls"] else "",
                        "text": b["text"],
                        "juice": b.get("juice", ""),
                        "category": b.get("category", "Uncategorized"),
                        "created_at": b["created_at"],
                        "created_label": bookmark_dt(b).strftime("%Y-%m-%d %H:%M UTC"),
                        "excerpt": short_excerpt(b),
                    }
                    for b in sorted_bookmarks
                    if (b.get("category") or "Uncategorized") == category
                ],
            }
        )

    return {
        "total": len(sorted_bookmarks),
        "date_range": {
            "first": bookmark_dt(sorted_bookmarks[-1]).strftime("%Y-%m-%d") if sorted_bookmarks else "",
            "last": bookmark_dt(sorted_bookmarks[0]).strftime("%Y-%m-%d") if sorted_bookmarks else "",
        },
        "top_category": category_counts.most_common(1)[0][0] if category_counts else "",
        "month_series": month_series,
        "heatmap": heatmap,
        "year_counts": [{"year": year, "count": year_counts[year]} for year in years],
        "categories": categories,
    }


def render_html(bookmarks: list[dict], analysis: str) -> str:
    data = build_dashboard_data(bookmarks)
    payload = json.dumps(data)
    analysis_html = "<br>".join(escape(line) for line in analysis.splitlines())
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X Bookmark Dashboard</title>
  <style>
    :root {{
      --bg: #f5efe2;
      --panel: rgba(255, 251, 245, 0.82);
      --panel-strong: #fffaf1;
      --ink: #1f241d;
      --muted: #646a61;
      --accent: #c85f38;
      --accent-2: #2f7d6b;
      --border: rgba(31, 36, 29, 0.09);
      --shadow: 0 18px 50px rgba(74, 52, 32, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(200, 95, 56, 0.18), transparent 26rem),
        radial-gradient(circle at top right, rgba(47, 125, 107, 0.18), transparent 30rem),
        linear-gradient(180deg, #f9f1e4 0%, #f1ebdf 100%);
    }}
    a {{ color: inherit; }}
    .shell {{
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 28px 22px;
      background: rgba(255, 249, 240, 0.9);
      backdrop-filter: blur(16px);
      border-right: 1px solid var(--border);
      overflow-y: auto;
    }}
    .brand {{
      margin-bottom: 24px;
    }}
    .brand h1 {{
      margin: 0;
      font-size: 1.7rem;
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    .brand p {{
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .search {{
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 13px 14px;
      background: white;
      margin: 0 0 18px;
      font: inherit;
    }}
    .category-list {{
      display: grid;
      gap: 10px;
    }}
    .category-button {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      width: 100%;
      border: 1px solid var(--border);
      background: var(--panel-strong);
      border-radius: 16px;
      padding: 12px 14px;
      cursor: pointer;
      font: inherit;
      text-align: left;
      box-shadow: 0 8px 20px rgba(31, 36, 29, 0.04);
    }}
    .category-button.active {{
      border-color: rgba(200, 95, 56, 0.35);
      background: linear-gradient(135deg, rgba(200, 95, 56, 0.14), rgba(47, 125, 107, 0.08));
    }}
    .category-count {{
      font-size: 0.85rem;
      color: var(--muted);
    }}
    .main {{
      padding: 28px;
    }}
    .hero {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 22px;
    }}
    .stat, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 20px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }}
    .stat .label {{
      color: var(--muted);
      font-size: 0.86rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .stat .value {{
      margin-top: 10px;
      font-size: 2rem;
      font-weight: 700;
      letter-spacing: -0.04em;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: 1.25fr 1fr;
      gap: 18px;
      margin-bottom: 18px;
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-size: 1.1rem;
      letter-spacing: -0.03em;
    }}
    .analysis {{
      color: #2f332d;
      line-height: 1.6;
    }}
    .bars {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(20px, 1fr));
      align-items: end;
      gap: 8px;
      min-height: 220px;
      padding-top: 10px;
    }}
    .bar-wrap {{
      display: flex;
      flex-direction: column;
      justify-content: end;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }}
    .bar {{
      width: 100%;
      min-height: 8px;
      border-radius: 999px 999px 6px 6px;
      background: linear-gradient(180deg, var(--accent), #e7b96b);
    }}
    .bar-label {{
      writing-mode: vertical-rl;
      transform: rotate(180deg);
      font-size: 0.72rem;
      color: var(--muted);
    }}
    .heatmap {{
      display: grid;
      gap: 10px;
    }}
    .heat-row {{
      display: grid;
      grid-template-columns: 62px repeat(12, minmax(0, 1fr));
      gap: 7px;
      align-items: center;
    }}
    .heat-year {{
      font-size: 0.82rem;
      color: var(--muted);
      font-weight: 600;
    }}
    .heat-cell {{
      aspect-ratio: 1 / 1;
      border-radius: 10px;
      border: 1px solid rgba(31, 36, 29, 0.05);
      display: grid;
      place-items: center;
      font-size: 0.7rem;
      color: rgba(0, 0, 0, 0.55);
    }}
    .month-head {{
      font-size: 0.7rem;
      color: var(--muted);
      text-align: center;
    }}
    .bookmark-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin: 18px 0;
    }}
    .bookmark-count {{
      color: var(--muted);
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 18px;
    }}
    .card {{
      background: rgba(255, 253, 249, 0.88);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 10px;
      background: rgba(47, 125, 107, 0.1);
      color: #215548;
    }}
    .excerpt {{
      margin: 0 0 12px;
      line-height: 1.55;
    }}
    .summary {{
      margin: 0 0 12px;
      color: #344137;
      line-height: 1.55;
    }}
    .links {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 0.9rem;
      margin-bottom: 12px;
    }}
    .preview {{
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 10px;
      min-height: 112px;
      background: #fff;
      overflow: hidden;
    }}
    .preview-note {{
      color: var(--muted);
      font-size: 0.8rem;
    }}
    @media (max-width: 1100px) {{
      .shell {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--border);
      }}
      .hero, .grid-2 {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <h1>X Bookmark Atlas</h1>
        <p>Browse your saved posts by category, then read the usage patterns hiding underneath.</p>
      </div>
      <input id="search" class="search" type="search" placeholder="Filter categories or bookmarks">
      <div id="category-list" class="category-list"></div>
    </aside>
    <main class="main">
      <section class="hero">
        <div class="stat"><div class="label">Bookmarks</div><div id="stat-total" class="value"></div></div>
        <div class="stat"><div class="label">Date Range</div><div id="stat-range" class="value" style="font-size:1.2rem"></div></div>
        <div class="stat"><div class="label">Top Category</div><div id="stat-category" class="value" style="font-size:1.3rem"></div></div>
        <div class="stat"><div class="label">Categories</div><div id="stat-categories" class="value"></div></div>
      </section>

      <section class="grid-2">
        <div class="panel">
          <h2>What Your Bookmarks Say</h2>
          <div class="analysis">{analysis_html}</div>
        </div>
        <div class="panel">
          <h2>Bookmarks By Month</h2>
          <div id="month-bars" class="bars"></div>
        </div>
      </section>

      <section class="grid-2">
        <div class="panel">
          <h2>Year / Month Heatmap</h2>
          <div id="heatmap" class="heatmap"></div>
        </div>
        <div class="panel">
          <h2>Yearly Totals</h2>
          <div id="year-bars" class="bars" style="min-height:180px"></div>
        </div>
      </section>

      <section class="panel">
        <div class="bookmark-toolbar">
          <div>
            <h2 id="current-category" style="margin:0 0 6px">All Categories</h2>
            <div id="bookmark-count" class="bookmark-count"></div>
          </div>
        </div>
        <div id="cards" class="cards"></div>
      </section>
    </main>
  </div>

  <script>
    const data = {payload};
    const state = {{
      category: "All",
      query: "",
    }};

    const categoryList = document.getElementById("category-list");
    const cards = document.getElementById("cards");
    const search = document.getElementById("search");
    const currentCategory = document.getElementById("current-category");
    const bookmarkCount = document.getElementById("bookmark-count");

    const statTotal = document.getElementById("stat-total");
    const statRange = document.getElementById("stat-range");
    const statCategory = document.getElementById("stat-category");
    const statCategories = document.getElementById("stat-categories");

    statTotal.textContent = data.total;
    statRange.textContent = `${{data.date_range.first}} → ${{data.date_range.last}}`;
    statCategory.textContent = data.top_category || "—";
    statCategories.textContent = data.categories.length;

    function colorForCount(count, max) {{
      if (!count) return "rgba(47, 125, 107, 0.06)";
      const ratio = Math.max(0.08, count / Math.max(max, 1));
      return `rgba(200, 95, 56, ${{0.15 + ratio * 0.75}})`;
    }}

    function renderBars() {{
      const monthBars = document.getElementById("month-bars");
      const yearBars = document.getElementById("year-bars");
      const maxMonth = Math.max(...data.month_series.map(item => item.count), 1);
      monthBars.innerHTML = data.month_series.map(item => `
        <div class="bar-wrap" title="${{item.month}}: ${{item.count}}">
          <div class="bar" style="height:${{Math.max(10, (item.count / maxMonth) * 180)}}px"></div>
          <div class="bar-label">${{item.month}}</div>
        </div>
      `).join("");

      const maxYear = Math.max(...data.year_counts.map(item => item.count), 1);
      yearBars.innerHTML = data.year_counts.map(item => `
        <div class="bar-wrap" title="${{item.year}}: ${{item.count}}">
          <div class="bar" style="height:${{Math.max(10, (item.count / maxYear) * 140)}}px;background:linear-gradient(180deg,var(--accent-2),#9fcdbf)"></div>
          <div class="bar-label">${{item.year}}</div>
        </div>
      `).join("");
    }}

    function renderHeatmap() {{
      const heatmap = document.getElementById("heatmap");
      const monthLabels = ["", "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      const max = Math.max(...data.month_series.map(item => item.count), 1);
      const header = `<div class="heat-row">${{monthLabels.map(label => `<div class="month-head">${{label}}</div>`).join("")}}</div>`;
      const rows = data.heatmap.map(row => `
        <div class="heat-row">
          <div class="heat-year">${{row.year}}</div>
          ${{row.months.map(cell => `<div class="heat-cell" title="${{cell.key}}: ${{cell.count}}" style="background:${{colorForCount(cell.count, max)}}">${{cell.count || ""}}</div>`).join("")}}
        </div>
      `).join("");
      heatmap.innerHTML = header + rows;
    }}

    function filteredCategories() {{
      const query = state.query.trim().toLowerCase();
      if (!query) return data.categories;
      return data.categories
        .map(category => {{
          const bookmarks = category.bookmarks.filter(bookmark =>
            [bookmark.author, bookmark.text, bookmark.juice, bookmark.category]
              .join(" ")
              .toLowerCase()
              .includes(query)
          );
          if (category.name.toLowerCase().includes(query) || bookmarks.length) {{
            return {{ ...category, bookmarks }};
          }}
          return null;
        }})
        .filter(Boolean);
    }}

    function renderCategories() {{
      const categories = filteredCategories();
      const allCount = categories.reduce((sum, item) => sum + item.bookmarks.length, 0);
      const buttons = [`
        <button class="category-button ${{state.category === "All" ? "active" : ""}}" data-category="All">
          <span>All Categories</span>
          <span class="category-count">${{allCount}}</span>
        </button>
      `];

      for (const category of categories) {{
        buttons.push(`
          <button class="category-button ${{state.category === category.name ? "active" : ""}}" data-category="${{category.name}}">
            <span>${{category.name}}</span>
            <span class="category-count">${{category.bookmarks.length}}</span>
          </button>
        `);
      }}

      categoryList.innerHTML = buttons.join("");
      categoryList.querySelectorAll(".category-button").forEach(button => {{
        button.addEventListener("click", () => {{
          state.category = button.dataset.category;
          renderCategories();
          renderCards();
        }});
      }});
    }}

    function currentBookmarks() {{
      const categories = filteredCategories();
      if (state.category === "All") {{
        return categories.flatMap(category => category.bookmarks)
          .sort((a, b) => b.created_at.localeCompare(a.created_at));
      }}
      const category = categories.find(item => item.name === state.category);
      return category ? category.bookmarks : [];
    }}

    function renderCards() {{
      const bookmarks = currentBookmarks();
      currentCategory.textContent = state.category === "All" ? "All Categories" : state.category;
      bookmarkCount.textContent = `${{bookmarks.length}} bookmarks`;

      cards.innerHTML = bookmarks.map(bookmark => `
        <article class="card">
          <div class="meta">
            <span class="pill">${{bookmark.created_label}}</span>
            <span class="pill">@${{bookmark.author || "unknown"}}</span>
          </div>
          <p class="excerpt">${{bookmark.excerpt || ""}}</p>
          <p class="summary">${{bookmark.juice || ""}}</p>
          <div class="links">
            <a href="${{bookmark.tweet_url}}" target="_blank" rel="noreferrer">Open post</a>
            ${{bookmark.resolved_url ? `<a href="${{bookmark.resolved_url}}" target="_blank" rel="noreferrer">Open article</a>` : ""}}
          </div>
          <div class="preview">
            <blockquote class="twitter-tweet" data-theme="light" data-conversation="none">
              <a href="${{bookmark.tweet_url}}"></a>
            </blockquote>
            <div class="preview-note">Embedded preview of the saved X post.</div>
          </div>
        </article>
      `).join("");

      if (window.twttr && window.twttr.widgets) {{
        window.twttr.widgets.load(cards);
      }}
    }}

    search.addEventListener("input", event => {{
      state.query = event.target.value;
      if (state.category !== "All") {{
        const exists = filteredCategories().some(item => item.name === state.category);
        if (!exists) state.category = "All";
      }}
      renderCategories();
      renderCards();
    }});

    renderBars();
    renderHeatmap();
    renderCategories();
    renderCards();
  </script>
  <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
</body>
</html>
"""


def write_markdown(bookmarks: list[dict], analysis: str) -> None:
    out = [
        "# Bookmark Analysis",
        f"_{time.strftime('%Y-%m-%d')} — {len(bookmarks)} bookmarks_\n",
        "## Analysis\n",
        analysis,
        "\n---\n",
        "## Categories\n",
    ]

    for category, count in Counter(b.get("category") or "Uncategorized" for b in bookmarks).most_common():
        out.append(f"- **{category}**: {count}")

    out.append("\n## All Bookmarks\n")
    for bookmark in bookmarks:
        timestamp = bookmark_dt(bookmark).strftime("%Y-%m-%d %H:%M UTC")
        out.append(f"**{timestamp} — @{bookmark['author']} — {bookmark['category']}**")
        out.append(bookmark.get("juice", ""))
        out.append(f"<{bookmark['tweet_url']}>")
        if bookmark.get("resolved_urls"):
            out.append(f"<{bookmark['resolved_urls'][0]}>")
        out.append(f"> {bookmark['text'][:250]}\n")

    OUTPUT.write_text("\n".join(out))


# --- Main ---

def main() -> None:
    existing = hydrate_bookmarks(json.loads(CACHE.read_text())) if CACHE.exists() else []

    if existing:
        print(f"Loading cached bookmarks from {CACHE}")
        print("Attempting to fetch only new bookmarks since the last run...")
        new_bookmarks = scrape_bookmarks({b["id"] for b in existing}, allow_failure=True)
    else:
        new_bookmarks = scrape_bookmarks()

    new_bookmarks = hydrate_bookmarks(new_bookmarks)
    bookmarks = merge_bookmarks(existing, new_bookmarks)
    save_cache(bookmarks)

    bookmarks = enrich(bookmarks)
    bookmarks = summarize_all(bookmarks)
    bookmarks = categorize_all(bookmarks)
    bookmarks = hydrate_bookmarks(bookmarks)
    save_cache(bookmarks)

    obsidian = read_obsidian()
    print("\nRunning interest analysis...")
    analysis = analyze(bookmarks, obsidian)

    write_markdown(bookmarks, analysis)
    HTML_OUTPUT.write_text(render_html(bookmarks, analysis))

    print(f"\nWritten markdown to {OUTPUT}")
    print(f"Written dashboard to {HTML_OUTPUT}\n")
    print("=" * 60)
    print(analysis)


if __name__ == "__main__":
    main()
