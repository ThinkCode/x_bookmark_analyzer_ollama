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
ENABLE_BOOKMARK_SUMMARIES = False
FORCE_REBUILD_CATEGORIES = True
ENABLE_OLLAMA_CATEGORY_FALLBACK = False
CATEGORY_TAXONOMY_VERSION = "2026-04-25-v2"

# Path.home() is your user home directory, for example /Users/kirankonathala.
OBSIDIAN_VAULT = None # Path("/Volumes/Projects/Obsidian Vault")

OUTPUT_DIR = OBSIDIAN_VAULT if OBSIDIAN_VAULT and OBSIDIAN_VAULT.exists() else Path.cwd()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CACHE = OUTPUT_DIR / "bookmarks_cache.json"
OUTPUT = OUTPUT_DIR / "bookmark_analysis.md"
HTML_OUTPUT = OUTPUT_DIR / "bookmark_dashboard.html"
CHECKPOINT = OUTPUT_DIR / "bookmark_checkpoint.json"
RESUME_LOG = OUTPUT_DIR / "bookmark_resume.log"

TWITTER_EPOCH = 1288834974657
CHECKPOINT_EVERY = 10
SCRAPE_TEST_LIMIT = None

FOLDER_CATEGORIES = [
    {
        "category_name": "Artificial Intelligence (AI) & LLMs",
        "description": "Topics covering the core concepts, models, training, and application of AI.",
        "items": [
            "AI Videos",
            "LLM Finetuning",
            "LLM Training",
            "Gemma Models",
            "Claude Skills",
            "AI Model API Keys",
            "LLM RAG",
            "AI Agents",
            "AI Agent Skills",
            "AI Vision LLM",
            "LLM Webscraper",
            "Local LLM",
            "Fine tuning DeepSeek",
            "AI Prompts",
            "AI Design Prompts",
            "AI Use Cases",
            "AI Investing",
            "AI SEO",
            "AI Tools Productivity",
            "AI Planning & Execution",
            "AI IDE",
            "AI Autoresearch",
            "Hermes",
        ],
    },
    {
        "category_name": "AI Tools & Agent Ecosystem",
        "description": "Focuses on practical tools, frameworks, platforms, and agent development.",
        "items": [
            "Agent Web Stack",
            "AI Tools for Agents",
            "AI Software Costs",
            "AI Github",
            "AI API",
            "OpenRouter",
            "OpenClaw",
            "AI Voice",
            "Telegram Bots",
            "Agentic Development",
        ],
    },
    {
        "category_name": "Programming & Development",
        "description": "Guides and topics related to coding, scripting, infrastructure, and software development.",
        "items": [
            "Python",
            "Python UV",
            "Github",
            "unsloth",
            "Write Tests in Code",
            "Web scraping",
            "Git Ingest",
            "Database Tips",
            "Log Management",
            "Server Optimization",
            "MCP Server",
            "Vector database",
            "Tailscale",
            "Codex",
            "Dashboards",
        ],
    },
    {
        "category_name": "System & Infrastructure",
        "description": "Topics related to hardware, hosting, operating systems, and deployment.",
        "items": [
            "Infrastructure hosting",
            "Local AI",
            "Mac Mini",
            "Server Optimization",
            "MCP",
            "Buildings and Floor Plans",
        ],
    },
    {
        "category_name": "Personal & Professional Growth",
        "description": "Covers career development, soft skills, personal finance, and self-improvement.",
        "items": [
            "Personal",
            "Productivity",
            "High Performer at Work",
            "Entrepreneurship",
            "Financial Wellness",
            "Retirement",
            "Immigration matters",
            "Success stories",
            "Content creator",
            "Skills",
            "LinkedIn Profile",
        ],
    },
    {
        "category_name": "Design & Creative Arts",
        "description": "Content focused on visual design, art, and creative expression.",
        "items": [
            "iOS Design",
            "Figma App design",
            "Design Ideas",
            "Painting hacks",
            "Handpan",
        ],
    },
    {
        "category_name": "Health & Wellness",
        "description": "Information related to physical fitness, health, and lifestyle.",
        "items": [
            "Health",
            "Fitness",
            "Healthy recipes",
            "Dumbbell Bench",
        ],
    },
    {
        "category_name": "Learning & Knowledge",
        "description": "Courses, academic topics, and educational content.",
        "items": [
            "Learning and Memory",
            "AI Courses",
            "Stanford courses",
            "eBooks",
            "Free Courses",
            "Write Papers",
            "Obsidian Memory",
        ],
    },
    {
        "category_name": "General & Miscellaneous",
        "description": "Catch-all categories for unique or unrelated topics.",
        "items": [
            "Personal",
            "Inspirational",
            "AI Security",
            "Security",
            "AI Voice",
        ],
    },
]


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


def normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


FOLDER_CATEGORY_INDEX = {}
for category in FOLDER_CATEGORIES:
    for item in category["items"]:
        FOLDER_CATEGORY_INDEX.setdefault(normalize_label(item), category["category_name"])

CATEGORY_NAME_INDEX = {
    normalize_label(category["category_name"]): category["category_name"]
    for category in FOLDER_CATEGORIES
}

TAXONOMY_PROMPT_BLOCK = "\n\n".join(
    (
        f"{category['category_name']}\n"
        f"Description: {category['description']}\n"
        f"Folder examples: {', '.join(category['items'])}"
    )
    for category in FOLDER_CATEGORIES
)


def folder_category_from_name(folder_name: str) -> str:
    return FOLDER_CATEGORY_INDEX.get(normalize_label(folder_name), "")


def taxonomy_category_from_text(*values: str) -> str:
    text = normalize_label(" ".join(value for value in values if value))
    if not text:
        return ""

    for item, category_name in FOLDER_CATEGORY_INDEX.items():
        if item and item in text:
            return category_name
    return ""


def categorize_from_folder(bookmark: dict) -> str:
    folder_category = folder_category_from_name(bookmark.get("folder_name", ""))
    bookmark["folder_category"] = folder_category
    return folder_category


def categorize_from_taxonomy(bookmark: dict) -> str:
    folder_category = categorize_from_folder(bookmark)
    if folder_category:
        return folder_category
    return taxonomy_category_from_text(
        bookmark.get("folder_name", ""),
        bookmark.get("text", ""),
        bookmark.get("juice", ""),
        bookmark.get("article_content", ""),
    )


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
    b.setdefault("category_source", "")
    b.setdefault("category_version", "")
    b.setdefault("folder_name", "")
    b["folder_category"] = folder_category_from_name(b.get("folder_name", ""))
    b.setdefault("created_at", timestamp_iso(b["id"]))
    return b


def hydrate_bookmarks(bookmarks: list[dict]) -> list[dict]:
    hydrated = [ensure_bookmark_defaults(b) for b in bookmarks]
    hydrated.sort(key=lambda b: b["created_at"], reverse=True)
    return hydrated


def save_cache(bookmarks: list[dict]) -> None:
    CACHE.write_text(json.dumps(bookmarks, indent=2))


def load_checkpoint() -> dict[str, dict]:
    if not CHECKPOINT.exists():
        return {}
    try:
        data = json.loads(CHECKPOINT.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_checkpoint(bookmarks: list[dict]) -> None:
    payload = {}
    for bookmark in bookmarks:
        entry = {}
        if bookmark.get("juice"):
            entry["juice"] = bookmark["juice"]
        if bookmark.get("category"):
            entry["category"] = bookmark["category"]
            entry["category_source"] = bookmark.get("category_source", "")
            entry["category_version"] = bookmark.get("category_version", "")
        if entry:
            payload[bookmark["id"]] = entry
    CHECKPOINT.write_text(json.dumps(payload, indent=2))


def apply_checkpoint(bookmarks: list[dict]) -> list[dict]:
    checkpoint = load_checkpoint()
    if not checkpoint:
        return bookmarks

    restored = 0
    for bookmark in bookmarks:
        entry = checkpoint.get(bookmark["id"])
        if not entry:
            continue
        if entry.get("juice") and not bookmark.get("juice"):
            bookmark["juice"] = entry["juice"]
            restored += 1
        if entry.get("category") and not bookmark.get("category"):
            bookmark["category"] = entry["category"]
            bookmark["category_source"] = entry.get("category_source", "")
            bookmark["category_version"] = entry.get("category_version", "")
            restored += 1

    if restored:
        print(f"Restored {restored} fields from {CHECKPOINT}")
    return bookmarks


def apply_summary_checkpoint(bookmarks: list[dict]) -> list[dict]:
    checkpoint = load_checkpoint()
    if not checkpoint:
        return bookmarks

    restored = 0
    for bookmark in bookmarks:
        entry = checkpoint.get(bookmark["id"])
        if entry and entry.get("juice") and not bookmark.get("juice"):
            bookmark["juice"] = entry["juice"]
            restored += 1

    if restored:
        print(f"Restored {restored} summary fields from {CHECKPOINT}")
    return bookmarks


def append_resume_log(stage: str, completed: int, total: int) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    RESUME_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RESUME_LOG.open("a") as handle:
        handle.write(f"{timestamp}\t{stage}\t{completed}/{total}\n")


def persist_progress(bookmarks: list[dict], stage: str, completed: int, total: int, force: bool = False) -> None:
    if total == 0:
        return
    if not force and completed % CHECKPOINT_EVERY != 0:
        return
    save_cache(bookmarks)
    save_checkpoint(bookmarks)
    append_resume_log(stage, completed, total)


def reset_categories(bookmarks: list[dict]) -> list[dict]:
    changed = 0
    for bookmark in bookmarks:
        folder_category = folder_category_from_name(bookmark.get("folder_name", ""))
        if folder_category != bookmark.get("folder_category", ""):
            bookmark["folder_category"] = folder_category
        if bookmark.get("category") or bookmark.get("category_source") or bookmark.get("category_version"):
            changed += 1
        bookmark["category"] = ""
        bookmark["category_source"] = ""
        bookmark["category_version"] = ""
    if changed:
        print(f"Reset {changed} existing categories for taxonomy rebuild.")
    return bookmarks


def bookmark_dt(bookmark: dict) -> datetime:
    return datetime.fromisoformat(bookmark["created_at"])


def merge_bookmarks(existing: list[dict], new: list[dict]) -> list[dict]:
    merged = {b["id"]: ensure_bookmark_defaults(b) for b in existing}
    for bookmark in new:
        merged[bookmark["id"]] = ensure_bookmark_defaults(bookmark)
    return sorted(merged.values(), key=lambda b: b["created_at"], reverse=True)


def cache_candidates() -> list[Path]:
    candidates = [CACHE, Path.cwd() / "bookmarks_cache.json"]
    unique = []
    for path in candidates:
        if path not in unique:
            unique.append(path)
    return unique


def bookmark_completeness(bookmarks: list[dict]) -> tuple[int, int, int]:
    return (
        len(bookmarks),
        sum(1 for b in bookmarks if b.get("juice")),
        sum(1 for b in bookmarks if b.get("category")),
    )


def load_existing_bookmarks() -> list[dict]:
    best_path = None
    best_bookmarks = []
    best_score = (-1, -1, -1)

    for path in cache_candidates():
        if not path.exists():
            continue
        try:
            bookmarks = hydrate_bookmarks(json.loads(path.read_text()))
        except Exception:
            continue
        score = bookmark_completeness(bookmarks)
        if score > best_score:
            best_path = path
            best_bookmarks = bookmarks
            best_score = score

    if best_path:
        print(f"Loading cache from {best_path}")
        print(
            "Cache status: "
            f"{best_score[0]} bookmarks, {best_score[1]} summarized, {best_score[2]} categorized"
        )
    return best_bookmarks


# --- Scraping ---

def extract_folder_names(page) -> list[str]:
    blacklist = {
        "all bookmarks",
        "search bookmarks",
        "bookmarks",
        "back",
        "new folder",
        "bookmark",
    }
    names = []
    seen = set()
    selectors = [
        '[data-testid="cellInnerDiv"]',
        'a[href*="/i/bookmarks"]',
        'div[role="button"]',
    ]

    for selector in selectors:
        for el in page.query_selector_all(selector):
            try:
                text = clean_text(el.inner_text())
            except Exception:
                continue
            if not text:
                continue
            text = text.split("\n")[0].strip()
            normalized = normalize_label(text)
            if (
                not normalized
                or normalized in blacklist
                or len(text) > 60
                or text.startswith("@")
                or text.isdigit()
            ):
                continue
            if text not in seen:
                seen.add(text)
                names.append(text)
    return names


def extract_bookmark_from_element(el, folder_name: str) -> dict | None:
    link = el.query_selector('a[href*="/status/"]')
    if not link:
        return None

    href = link.get_attribute("href") or ""
    match = re.search(r"/status/(\d+)", href)
    if not match:
        return None

    tid = match.group(1)
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

    return {
        "id": tid,
        "author": author,
        "text": text,
        "tweet_url": f"https://x.com/i/web/status/{tid}",
        "external_urls": sorted(set(urls)),
        "resolved_urls": [],
        "article_content": "",
        "juice": "",
        "category": "",
        "folder_name": folder_name,
        "folder_category": folder_category_from_name(folder_name),
        "created_at": timestamp_iso(tid),
    }


def update_existing_folder_metadata(existing_by_id: dict[str, dict], bookmark: dict, folder_name: str) -> bool:
    existing = existing_by_id.get(bookmark["id"])
    if not existing:
        return False
    changed = False
    if folder_name and existing.get("folder_name") != folder_name:
        existing["folder_name"] = folder_name
        changed = True
    folder_category = folder_category_from_name(folder_name)
    if folder_category and existing.get("folder_category") != folder_category:
        existing["folder_category"] = folder_category
        changed = True
    return changed


def collect_bookmarks_from_timeline(
    page,
    seen: set[str],
    folder_name: str,
    limit: int | None,
    existing_by_id: dict[str, dict] | None = None,
) -> tuple[list[dict], bool, int]:
    bookmarks = []
    metadata_updates = 0
    no_new = 0
    while no_new < 5:
        tweet_els = page.query_selector_all('[data-testid="tweet"]')
        new = 0

        for el in tweet_els:
            try:
                bookmark = extract_bookmark_from_element(el, folder_name)
                if not bookmark:
                    continue
                if bookmark["id"] in seen:
                    if existing_by_id and update_existing_folder_metadata(existing_by_id, bookmark, folder_name):
                        metadata_updates += 1
                    continue
                seen.add(bookmark["id"])
                bookmarks.append(bookmark)
                new += 1
                if limit is not None and len(bookmarks) >= limit:
                    return bookmarks, True, metadata_updates
            except Exception:
                continue

        no_new = no_new + 1 if new == 0 else 0
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2.0)
        print(f"  {len(bookmarks)} new bookmarks collected...", end="\r")

    return bookmarks, False, metadata_updates


def open_folder(page, folder_name: str) -> bool:
    try:
        page.get_by_text(folder_name, exact=True).first.click(timeout=5000)
        page.wait_for_timeout(1500)
        return True
    except Exception:
        return False


def bookmarks_surface_ready(page) -> bool:
    selectors = [
        '[data-testid="tweet"]',
        'input[placeholder*="Search Bookmarks"]',
        '[data-testid="cellInnerDiv"]',
    ]
    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


def wait_for_bookmarks_surface(page, timeout_ms: int) -> bool:
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        if bookmarks_surface_ready(page):
            return True
        page.wait_for_timeout(750)
    return bookmarks_surface_ready(page)


def scrape_bookmarks(
    existing_ids: set[str] | None = None,
    allow_failure: bool = False,
    stop_on_first_stale_folder: bool = False,
    existing_bookmarks: list[dict] | None = None,
) -> list[dict]:
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
    limit = SCRAPE_TEST_LIMIT
    existing_by_id = {bookmark["id"]: bookmark for bookmark in existing_bookmarks or []}
    metadata_updates = 0

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
        if not wait_for_bookmarks_surface(page, 15000):
            if allow_failure:
                print("Bookmarks did not load from Chrome. Continuing with cached bookmarks only.")
                page.close()
                browser.close()
                return []
            print("\nX bookmarks did not load yet.")
            print("Log into X in your Chrome window, then press Enter here to continue.")
            input()
            page.goto("https://x.com/i/bookmarks")
            if not wait_for_bookmarks_surface(page, 120000):
                print("Still could not detect the bookmarks page after waiting.")
                page.close()
                browser.close()
                sys.exit(1)

        page.wait_for_timeout(1500)
        folder_names = extract_folder_names(page)

        if folder_names:
            print(f"Found {len(folder_names)} bookmark folders. Test mode limit: {limit} bookmarks.")
            for folder_name in folder_names:
                if limit is not None and len(bookmarks) >= limit:
                    break
                print(f"\nOpening folder: {folder_name}")
                if not open_folder(page, folder_name):
                    continue
                folder_bookmarks, reached_limit, folder_metadata_updates = collect_bookmarks_from_timeline(
                    page,
                    seen,
                    folder_name,
                    None if limit is None else max(limit - len(bookmarks), 0),
                    existing_by_id,
                )
                bookmarks.extend(folder_bookmarks)
                metadata_updates += folder_metadata_updates
                if reached_limit:
                    break
                if stop_on_first_stale_folder and not folder_bookmarks:
                    print(f"\nNo new bookmarks in folder '{folder_name}'. Stopping incremental scan.")
                    break
                page.goto("https://x.com/i/bookmarks")
                page.wait_for_timeout(1500)
        else:
            fallback_bookmarks, _, folder_metadata_updates = collect_bookmarks_from_timeline(
                page,
                seen,
                "",
                limit,
                existing_by_id,
            )
            bookmarks.extend(fallback_bookmarks)
            metadata_updates += folder_metadata_updates

        page.close()
        browser.close()

    if metadata_updates:
        print(f"\nUpdated folder metadata for {metadata_updates} existing bookmarks.")
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

def ollama_chat(prompt: str, max_tokens: int, timeout: float = 120) -> str:
    try:
        r = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_predict": max_tokens},
            },
            timeout=timeout,
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
    taxonomy_category = categorize_from_taxonomy(bookmark)
    if taxonomy_category:
        return taxonomy_category

    if not ENABLE_OLLAMA_CATEGORY_FALLBACK:
        return "Uncategorized"

    content = clean_text(bookmark.get("juice") or bookmark.get("text") or "")
    article = clean_text(bookmark.get("article_content", ""))[:1000]
    folder_name = clean_text(bookmark.get("folder_name", ""))
    prompt = f"""Categorize this X bookmark using the taxonomy below.

            Prefer returning exactly one existing taxonomy category name.
            If none fit well enough, create a short new category label in Title Case.
            Return only the category label. No explanation.

            Taxonomy:
            {TAXONOMY_PROMPT_BLOCK}

            Folder name metadata:
            {folder_name or "(none)"}

            Bookmark text:
            {content or "(none)"}

            Article excerpt:
            {article or "(none)"}
            """
    fallback_parts = []
    if folder_name:
        fallback_parts.append(folder_name)
    if content:
        fallback_parts.append(content)
    if article:
        fallback_parts.append(article)
    fallback_source = " ".join(fallback_parts).strip()

    for _ in range(2):
        raw = ollama_chat(prompt, max_tokens=20).strip()
        first_line = raw.splitlines()[0].strip() if raw.splitlines() else ""
        category = re.sub(r"[^A-Za-z0-9 /&+-]", "", first_line.strip('"').strip("'")).strip()
        if category:
            matched_taxonomy = CATEGORY_NAME_INDEX.get(normalize_label(category))
            if matched_taxonomy:
                return matched_taxonomy
            return category[:40]

    if fallback_source:
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&+-]*", fallback_source)
        if words:
            return " ".join(word.capitalize() for word in words[:3])[:40]

    return "Uncategorized"


def summarize_all(bookmarks: list[dict]) -> list[dict]:
    if not ENABLE_BOOKMARK_SUMMARIES:
        print("\nSkipping per-bookmark summaries. Using raw text/article content instead.")
        return bookmarks
    pending = sum(1 for b in bookmarks if not b.get("juice"))
    print(f"\nSummarizing {len(bookmarks)} bookmarks... ({pending} pending)")
    completed = 0
    for i, bookmark in enumerate(bookmarks):
        if bookmark.get("juice"):
            continue
        print(f"  {i+1}/{len(bookmarks)}: @{bookmark['author'][:25]}", end="\r")
        bookmark["juice"] = get_juice(bookmark)
        completed += 1
        persist_progress(bookmarks, "summarize", completed, pending)
    persist_progress(bookmarks, "summarize", completed, pending, force=True)
    return bookmarks


def categorize_all(bookmarks: list[dict]) -> list[dict]:
    pending = sum(1 for b in bookmarks if not b.get("category"))
    print(f"\nCategorizing {len(bookmarks)} bookmarks... ({pending} pending)")
    completed = 0
    folder_hits = 0
    taxonomy_hits = 0
    ollama_hits = 0
    uncategorized_hits = 0
    for i, bookmark in enumerate(bookmarks):
        if bookmark.get("category"):
            continue
        print(f"  {i+1}/{len(bookmarks)}: @{bookmark['author'][:25]}", end="\r")
        folder_category = categorize_from_folder(bookmark)
        if folder_category:
            bookmark["category"] = folder_category
            bookmark["category_source"] = "folder_taxonomy"
            bookmark["category_version"] = CATEGORY_TAXONOMY_VERSION
            completed += 1
            folder_hits += 1
            persist_progress(bookmarks, "categorize", completed, pending)
            continue

        taxonomy_category = taxonomy_category_from_text(
            bookmark.get("text", ""),
            bookmark.get("juice", ""),
            bookmark.get("article_content", ""),
        )
        if taxonomy_category:
            bookmark["category"] = taxonomy_category
            bookmark["category_source"] = "taxonomy_keyword"
            bookmark["category_version"] = CATEGORY_TAXONOMY_VERSION
            completed += 1
            taxonomy_hits += 1
            persist_progress(bookmarks, "categorize", completed, pending)
            continue

        bookmark["category"] = get_category(bookmark)
        bookmark["category_source"] = "ollama_taxonomy" if bookmark["category"] != "Uncategorized" else "taxonomy_unmatched"
        bookmark["category_version"] = CATEGORY_TAXONOMY_VERSION
        completed += 1
        if bookmark["category"] == "Uncategorized":
            uncategorized_hits += 1
        else:
            ollama_hits += 1
        persist_progress(bookmarks, "categorize", completed, pending)
    persist_progress(bookmarks, "categorize", completed, pending, force=True)
    if pending:
        print(
            f"\nCategorized {pending} bookmarks: "
            f"{folder_hits} from folder taxonomy, "
            f"{taxonomy_hits} from taxonomy keywords, "
            f"{ollama_hits} via Ollama, "
            f"{uncategorized_hits} unmatched."
        )
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


def build_analysis_digest(bookmarks: list[dict]) -> str:
    category_buckets = {}
    for bookmark in bookmarks:
        category = bookmark.get("category") or "Uncategorized"
        category_buckets.setdefault(category, []).append(bookmark)

    lines = []
    for category, items in sorted(category_buckets.items(), key=lambda pair: len(pair[1]), reverse=True)[:12]:
        lines.append(f"## {category} ({len(items)})")
        for bookmark in items[:4]:
            summary = clean_text(bookmark.get("juice") or bookmark.get("text") or "")
            if len(summary) > 180:
                summary = summary[:179].rstrip() + "…"
            line = f"- {bookmark['created_at']} | @{bookmark['author']}: {summary}"
            if bookmark["resolved_urls"]:
                line += f" | {bookmark['resolved_urls'][0]}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()


def analyze(bookmarks: list[dict], obsidian: str) -> str:
    category_counts = Counter(b.get("category") or "Uncategorized" for b in bookmarks)
    yearly_counts = Counter(year_key(b) for b in bookmarks)
    top_categories = "\n".join(
        f"- {category}: {count}"
        for category, count in category_counts.most_common(12)
    )
    yearly_summary = "\n".join(
        f"- {year}: {count}"
        for year, count in sorted(yearly_counts.items())
    )
    bookmark_digest = build_analysis_digest(bookmarks)

    obsidian_section = obsidian if obsidian else "(No Obsidian notes provided.)"

    prompt = f"""You're doing an honest, direct analysis of someone's X bookmarks.

Here is the bookmark distribution by category:

{top_categories}

Here is the bookmark distribution by year:

{yearly_summary}

Here is a representative sample of bookmarks, grouped by category:

{bookmark_digest}

Their Obsidian notes (if any):
{obsidian_section}

Give them:

1. Real themes - 3 to 5 specific interests you see across these bookmarks.
2. Surprises - anything unexpected or non-obvious about what they're saving.
3. One clear direction - what they should build or pursue next.
4. Tensions - contradictions or tradeoffs in their interests.

Keep it sharp, specific, and peer-level."""

    return ollama_chat(prompt, max_tokens=1800, timeout=600)


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
                        "folder_name": b.get("folder_name", ""),
                        "folder_category": b.get("folder_category", ""),
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
            ${{bookmark.folder_name ? `<span class="pill">Folder: ${{bookmark.folder_name}}</span>` : ""}}
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
        if bookmark.get("folder_name"):
            out.append(f"Folder: {bookmark['folder_name']}")
        out.append(bookmark.get("juice") or short_excerpt(bookmark, length=320))
        out.append(f"<{bookmark['tweet_url']}>")
        if bookmark.get("resolved_urls"):
            out.append(f"<{bookmark['resolved_urls'][0]}>")
        out.append(f"> {bookmark['text'][:250]}\n")

    OUTPUT.write_text("\n".join(out))


# --- Main ---

def main() -> None:
    existing = load_existing_bookmarks()
    if FORCE_REBUILD_CATEGORIES and existing:
        existing = apply_summary_checkpoint(existing)
        existing = reset_categories(existing)
        save_cache(existing)
        save_checkpoint(existing)
    else:
        existing = apply_checkpoint(existing)

    if existing:
        missing_folder_metadata = sum(1 for bookmark in existing if not bookmark.get("folder_name"))
        stop_on_first_stale_folder = missing_folder_metadata == 0
        if missing_folder_metadata:
            print(f"Backfilling folder metadata for {missing_folder_metadata} cached bookmarks before using early-stop scanning.")
        print("Attempting to fetch only new bookmarks since the last run...")
        new_bookmarks = scrape_bookmarks(
            {b["id"] for b in existing},
            allow_failure=True,
            stop_on_first_stale_folder=stop_on_first_stale_folder,
            existing_bookmarks=existing,
        )
    else:
        new_bookmarks = scrape_bookmarks()

    new_bookmarks = hydrate_bookmarks(new_bookmarks)
    bookmarks = merge_bookmarks(existing, new_bookmarks)
    save_cache(bookmarks)
    save_checkpoint(bookmarks)

    bookmarks = enrich(bookmarks)
    bookmarks = summarize_all(bookmarks)
    bookmarks = categorize_all(bookmarks)
    bookmarks = hydrate_bookmarks(bookmarks)
    save_cache(bookmarks)
    save_checkpoint(bookmarks)

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
