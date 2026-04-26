"""Ollama-backed summarization, categorization, and interest analysis."""
import sys
from collections import Counter

import httpx

from .config import (
    ENABLE_BOOKMARK_SUMMARIES,
    ENABLE_OLLAMA_CATEGORY_FALLBACK,
    MODEL,
    OBSIDIAN_VAULT,
    OLLAMA_URL,
    CATEGORY_TAXONOMY_VERSION,
)
from .dashboard import year_key
from .models import (
    CATEGORY_NAME_INDEX,
    TAXONOMY_PROMPT_BLOCK,
    bookmark_dt,
    categorize_from_folder,
    categorize_from_taxonomy,
    clean_text,
    normalize_label,
    persist_progress,
    taxonomy_category_from_text,
)

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

0. A brutally honest summary/analysis of their interests based on these bookmarks at the top, drop this at the top: 'This is the analysis of the bookmark data.' Come straight to the point.
1. Real themes - 3 to 5 specific interests you see across these bookmarks.
2. Surprises - anything unexpected or non-obvious about what they're saving.
3. One clear direction - what they should build or pursue next.
4. Tensions - contradictions or tradeoffs in their interests.

Keep it sharp, specific, and peer-level."""

    return ollama_chat(prompt, max_tokens=1800, timeout=600)
