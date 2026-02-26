"""Fetch daily papers from HuggingFace API."""
import json
import httpx
from datetime import date
from .config import DATA_DIR

HF_API = "https://huggingface.co/api/daily_papers"


def fetch_daily_papers(target_date: date) -> list[dict]:
    """Return list of paper dicts for the given date. Uses local cache."""
    date_str = target_date.isoformat()
    cache_path = DATA_DIR / date_str / "papers.json"

    if cache_path.exists():
        print(f"[fetch] Using cache for {date_str}")
        return json.loads(cache_path.read_text())

    print(f"[fetch] Fetching papers for {date_str} from HF API...")
    resp = httpx.get(HF_API, params={"date": date_str}, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    # Normalize: HF returns a list of objects, each with a "paper" key
    papers = []
    for item in raw:
        p = item.get("paper", item)  # handle both formats
        papers.append({
            "arxiv_id": p.get("id", ""),
            "title": p.get("title", ""),
            "abstract": p.get("summary", p.get("abstract", "")),
            "authors": [a.get("name", a) if isinstance(a, dict) else a
                        for a in p.get("authors", [])],
            "upvotes": item.get("numComments", 0) or p.get("upvotes", 0),
            "published_at": p.get("publishedAt", ""),
        })

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(papers, ensure_ascii=False, indent=2))
    print(f"[fetch] Found {len(papers)} papers")
    return papers
