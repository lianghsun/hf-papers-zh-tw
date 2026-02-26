"""Main pipeline: fetch → parse (HTML or PDF) → translate → build site → email."""
import sys
import json
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import DATA_DIR
from .fetch_papers import fetch_daily_papers
from .download_pdf import download_pdf
from .parse_arxiv_html import parse_arxiv_html
from .parse_pdf import parse_pdf
from .translate import translate_abstract, translate_title, translate_markdown
from .generate_tags import generate_tags
from .build_site import build_site
from .send_email import send_daily_digest


def _translate_paper_meta(paper: dict, date_str: str) -> dict:
    """Translate abstract + title + generate tags. Fast, run first."""
    arxiv_id = paper["arxiv_id"]

    # Abstract
    cache = DATA_DIR / date_str / arxiv_id / "abstract_zh.txt"
    if cache.exists():
        paper["abstract_zh"] = cache.read_text(encoding="utf-8")
    else:
        try:
            paper["abstract_zh"] = translate_abstract(paper["abstract"])
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(paper["abstract_zh"], encoding="utf-8")
        except Exception as e:
            print(f"[meta] Abstract translation failed {arxiv_id}: {e}")
            paper["abstract_zh"] = ""

    # Title
    cache = DATA_DIR / date_str / arxiv_id / "title_zh.txt"
    if cache.exists():
        paper["title_zh"] = cache.read_text(encoding="utf-8")
    else:
        try:
            paper["title_zh"] = translate_title(paper["title"])
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(paper["title_zh"], encoding="utf-8")
        except Exception as e:
            print(f"[meta] Title translation failed {arxiv_id}: {e}")
            paper["title_zh"] = ""

    # Tags
    try:
        paper["tags"] = generate_tags(paper["title"], paper["abstract"], arxiv_id, date_str)
    except Exception as e:
        print(f"[meta] Tags failed {arxiv_id}: {e}")
        paper["tags"] = {"domain": [], "method": [], "task": [], "dataset": [], "open_source": False}

    return paper


def process_paper(paper: dict, date_str: str) -> dict:
    """Full pipeline for a single paper."""
    arxiv_id = paper["arxiv_id"]
    print(f"\n{'='*60}\nProcessing: {arxiv_id}\n{paper['title'][:70]}\n{'='*60}")

    # Step 1: meta (fast)
    paper = _translate_paper_meta(paper, date_str)

    # Step 2: parse content — try HTML first, fall back to PDF
    parsed = parse_arxiv_html(arxiv_id, date_str)

    if parsed is None:
        print(f"[main] No HTML version, falling back to PDF for {arxiv_id}")
        pdf_path = download_pdf(arxiv_id, date_str)
        if pdf_path is None:
            print(f"[main] PDF download failed for {arxiv_id}, skipping content")
            paper["content_md_zh"] = ""
            paper["figures"] = []
            return paper
        try:
            parsed = parse_pdf(pdf_path, arxiv_id, date_str)
        except Exception as e:
            print(f"[main] PDF parse failed {arxiv_id}: {e}")
            paper["content_md_zh"] = ""
            paper["figures"] = []
            return paper

    # Step 3: translate full content
    markdown = parsed.get("markdown", "")
    paper["figures"] = parsed.get("figures", [])
    paper["parse_source"] = parsed.get("source", "unknown")

    if markdown:
        try:
            paper["content_md_zh"] = translate_markdown(markdown, arxiv_id, date_str)
        except Exception as e:
            print(f"[main] Translation failed {arxiv_id}: {e}")
            paper["content_md_zh"] = markdown  # fallback: untranslated
    else:
        paper["content_md_zh"] = ""

    return paper


def run(target_date: date | None = None) -> None:
    if target_date is None:
        target_date = date.today()
    date_str = target_date.isoformat()
    print(f"\n{'#'*60}\nHF Papers pipeline — {date_str}\n{'#'*60}\n")

    papers = fetch_daily_papers(target_date)
    if not papers:
        print(f"[main] No papers for {date_str}, exiting")
        return

    print(f"[main] Processing {len(papers)} papers with ThreadPoolExecutor...")
    enriched: list[dict] = [None] * len(papers)

    with ThreadPoolExecutor(max_workers=3) as ex:
        future_to_idx = {
            ex.submit(process_paper, dict(p), date_str): i
            for i, p in enumerate(papers)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                enriched[idx] = future.result()
            except Exception as e:
                print(f"[main] Paper {idx} ERROR: {e}")
                enriched[idx] = papers[idx]

    enriched = [p for p in enriched if p is not None]

    print(f"\n[main] Building site...")
    build_site(date_str, enriched)

    print(f"\n[main] Sending email...")
    try:
        send_daily_digest(date_str, enriched)
    except Exception as e:
        print(f"[main] Email failed (non-fatal): {e}")

    print(f"\n[main] Done! {len(enriched)} papers for {date_str}")


if __name__ == "__main__":
    target = None
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    run(target)
