"""External URL resolution and article enrichment for bookmarks."""

from .article import fetch_article, resolve_url
from .models import save_cache

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
