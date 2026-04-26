"""Bookmark normalization, taxonomy matching, cache, and checkpoint helpers."""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    CACHE,
    CATEGORY_TAXONOMY_VERSION,
    CHECKPOINT,
    CHECKPOINT_EVERY,
    FOLDER_CATEGORIES,
    RESUME_LOG,
    TWITTER_EPOCH,
)

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
