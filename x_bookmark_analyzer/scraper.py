"""X bookmark scraping through an existing Chrome CDP session."""
import re
import subprocess
import sys
import time
from urllib.parse import urlparse

from .config import CDP_URL, FOLDER_SCAN_STABLE_SCROLLS, SCRAPE_TEST_LIMIT
from .models import clean_text, folder_category_from_name, normalize_label, timestamp_iso

# --- Scraping ---

FAST_WAIT_MS = 250
FOLDER_RENDER_WAIT_MS = 700
TIMELINE_RENDER_WAIT_MS = 1200
TIMELINE_STABLE_SCROLLS = 3
FOLDER_SCROLL_OFFSETS: dict[str, int] = {}
CHROME_CDP_PROFILE = "/tmp/chrome-playwright-x"

FOLDER_BLACKLIST = {
    "all bookmarks",
    "back",
    "bookmarks",
    "communities",
    "explore",
    "grok",
    "home",
    "jobs",
    "lists",
    "messages",
    "more",
    "new folder",
    "notifications",
    "post",
    "premium",
    "profile",
    "search",
    "search bookmarks",
    "verified orgs",
    "bookmark",
}


def is_folder_name(value: str) -> bool:
    normalized = normalize_label(value)
    return bool(
        normalized
        and normalized not in FOLDER_BLACKLIST
        and len(value) <= 60
        and not value.startswith("@")
        and not value.isdigit()
    )


def extract_visible_folder_names(page) -> list[str]:
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
            if is_folder_name(text) and text not in seen:
                seen.add(text)
                names.append(text)
    return names


def scroll_metrics(page) -> dict:
    return page.evaluate(
        """() => ({
            y: Math.round(window.scrollY),
            height: Math.round(document.body.scrollHeight),
            innerHeight: Math.round(window.innerHeight)
        })"""
    )


def visible_tweet_ids(page) -> list[str]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/status/"]'))
            .map((anchor) => anchor.href.match(/\\/status\\/(\\d+)/)?.[1])
            .filter(Boolean)"""
    )


def wait_for_folder_scroll_update(page, before_names: list[str], before_metrics: dict) -> None:
    try:
        page.wait_for_function(
            """({ beforeNames, beforeY, beforeHeight }) => {
                const names = Array.from(document.querySelectorAll(
                    '[data-testid="cellInnerDiv"], a[href*="/i/bookmarks"], div[role="button"]'
                ))
                    .map((el) => (el.innerText || "").split("\\n")[0].trim())
                    .filter(Boolean);
                return Math.round(window.scrollY) !== beforeY ||
                    Math.round(document.body.scrollHeight) !== beforeHeight ||
                    names.some((name) => !beforeNames.includes(name));
            }""",
            arg={
                "beforeNames": before_names,
                "beforeY": before_metrics["y"],
                "beforeHeight": before_metrics["height"],
            },
            timeout=FOLDER_RENDER_WAIT_MS,
        )
    except Exception:
        pass


def wait_for_timeline_update(page, before_ids: list[str], before_metrics: dict) -> bool:
    try:
        page.wait_for_function(
            """({ beforeIds, beforeY, beforeHeight }) => {
                const ids = Array.from(document.querySelectorAll('a[href*="/status/"]'))
                    .map((anchor) => anchor.href.match(/\\/status\\/(\\d+)/)?.[1])
                    .filter(Boolean);
                return ids.some((id) => !beforeIds.includes(id)) ||
                    Math.round(window.scrollY) !== beforeY ||
                    Math.round(document.body.scrollHeight) !== beforeHeight;
            }""",
            arg={
                "beforeIds": before_ids,
                "beforeY": before_metrics["y"],
                "beforeHeight": before_metrics["height"],
            },
            timeout=TIMELINE_RENDER_WAIT_MS,
        )
        return True
    except Exception:
        return False


def wait_for_top(page) -> None:
    try:
        page.wait_for_function("() => Math.round(window.scrollY) === 0", timeout=FAST_WAIT_MS)
    except Exception:
        pass


def chrome_cdp_launch_command() -> list[str]:
    port = urlparse(CDP_URL).port or 9222
    return [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={CHROME_CDP_PROFILE}",
    ]


def connect_chrome_over_cdp(playwright, allow_failure: bool):
    print(f"Connecting to existing Chrome via CDP: {CDP_URL}")
    try:
        return playwright.chromium.connect_over_cdp(CDP_URL)
    except Exception:
        pass

    if sys.platform == "darwin":
        command = chrome_cdp_launch_command()
        print("\nCould not connect to Chrome over CDP. Starting a dedicated Chrome debugging window...")
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            print(f"Could not launch Chrome automatically: {exc}")
        else:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                try:
                    return playwright.chromium.connect_over_cdp(CDP_URL)
                except Exception:
                    time.sleep(0.5)

    if allow_failure:
        print("\nCould not connect to Chrome over CDP. Continuing with cached bookmarks only.")
        return None

    print("\nCould not connect to Chrome over CDP.")
    print("Launch Chrome with this command first:")
    print(f"  {' '.join(chrome_cdp_launch_command())}")
    print("Then open x.com, log in, and run this script again.")
    sys.exit(1)


def extract_folder_names(page) -> list[str]:
    """Scroll the virtualized X folder list until no new folder names appear."""
    names = []
    seen = set()
    FOLDER_SCROLL_OFFSETS.clear()
    stable_scrolls = 0
    last_scroll_y = -1
    last_height = -1

    page.evaluate("window.scrollTo(0, 0)")
    wait_for_top(page)

    while stable_scrolls < FOLDER_SCAN_STABLE_SCROLLS:
        new_names = 0
        for name in extract_visible_folder_names(page):
            if name not in seen:
                seen.add(name)
                names.append(name)
                FOLDER_SCROLL_OFFSETS[name] = scroll_metrics(page)["y"]
                new_names += 1

        before_names = extract_visible_folder_names(page)
        metrics = scroll_metrics(page)
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
        wait_for_folder_scroll_update(page, before_names, metrics)
        next_metrics = scroll_metrics(page)

        moved = next_metrics["y"] != metrics["y"]
        height_changed = next_metrics["height"] != metrics["height"]
        if new_names or moved or height_changed or metrics["y"] != last_scroll_y or metrics["height"] != last_height:
            stable_scrolls = 0 if new_names else stable_scrolls + 1
        else:
            stable_scrolls += 1

        last_scroll_y = next_metrics["y"]
        last_height = next_metrics["height"]
        print(f"  {len(names)} bookmark folders discovered...", end="\r")

    page.evaluate("window.scrollTo(0, 0)")
    wait_for_top(page)
    print(f"  {len(names)} bookmark folders discovered.")
    return names


def find_folder_button(page, folder_name: str):
    try:
        candidate = page.get_by_text(folder_name, exact=True).first
        candidate.wait_for(timeout=FAST_WAIT_MS)
        return candidate
    except Exception:
        return None


def scroll_to_folder(page, folder_name: str) -> bool:
    offset = FOLDER_SCROLL_OFFSETS.get(folder_name, 0)
    page.evaluate(
        "(offset) => window.scrollTo(0, Math.max(0, offset - window.innerHeight * 0.25))",
        offset,
    )
    stable_scrolls = 0
    last_scroll_y = -1
    last_height = -1

    while stable_scrolls < FOLDER_SCAN_STABLE_SCROLLS:
        if find_folder_button(page, folder_name):
            return True

        before_names = extract_visible_folder_names(page)
        metrics = scroll_metrics(page)
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
        wait_for_folder_scroll_update(page, before_names, metrics)
        next_metrics = scroll_metrics(page)

        if next_metrics["y"] == last_scroll_y and next_metrics["height"] == last_height:
            stable_scrolls += 1
        else:
            stable_scrolls = 0 if next_metrics["y"] != metrics["y"] else stable_scrolls + 1
        last_scroll_y = next_metrics["y"]
        last_height = next_metrics["height"]

    return bool(find_folder_button(page, folder_name))


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
    while no_new < TIMELINE_STABLE_SCROLLS:
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
        before_ids = visible_tweet_ids(page)
        before_metrics = scroll_metrics(page)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        updated = wait_for_timeline_update(page, before_ids, before_metrics)
        if not updated and before_metrics["y"] + before_metrics["innerHeight"] >= before_metrics["height"] - 2:
            no_new = TIMELINE_STABLE_SCROLLS
        print(f"  {len(bookmarks)} new bookmarks collected...", end="\r")

    return bookmarks, False, metadata_updates


def open_folder(page, folder_name: str) -> bool:
    try:
        if not scroll_to_folder(page, folder_name):
            return False
        before_url = page.url
        before_ids = visible_tweet_ids(page)
        page.get_by_text(folder_name, exact=True).first.click(timeout=5000)
        try:
            page.wait_for_function(
                """({ beforeUrl, beforeIds }) => {
                    const ids = Array.from(document.querySelectorAll('a[href*="/status/"]'))
                        .map((anchor) => anchor.href.match(/\\/status\\/(\\d+)/)?.[1])
                        .filter(Boolean);
                    return location.href !== beforeUrl ||
                        ids.some((id) => !beforeIds.includes(id));
                }""",
                arg={"beforeUrl": before_url, "beforeIds": before_ids},
                timeout=5000,
            )
        except Exception:
            return bookmarks_surface_ready(page)
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
    try:
        page.wait_for_function(
            """() => Boolean(
                document.querySelector('[data-testid="tweet"]') ||
                document.querySelector('input[placeholder*="Search Bookmarks"]') ||
                document.querySelector('[data-testid="cellInnerDiv"]')
            )""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        pass
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
        browser = connect_chrome_over_cdp(p, allow_failure)
        if browser is None:
            return []

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

        wait_for_bookmarks_surface(page, 5000)
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
                wait_for_bookmarks_surface(page, 5000)
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
