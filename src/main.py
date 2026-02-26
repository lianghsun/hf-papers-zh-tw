"""Main pipeline: fetch → download → parse → translate → tag → build → email."""
import sys
import json
from datetime import date, timedelta
from pathlib import Path

from .config import DATA_DIR
from .fetch_papers import fetch_daily_papers
from .download_pdf import download_pdf
from .parse_pdf import parse_pdf
from .translate import translate_abstract, translate_paper_content
from .generate_tags import generate_tags
from .build_site import build_site
from .send_email import send_daily_digest


def process_paper(paper: dict, date_str: str) -> dict:
    """Full pipeline for a single paper. Returns enriched paper dict."""
    arxiv_id = paper["arxiv_id"]
    print(f"\n{'='*60}")
    print(f"Processing: {arxiv_id}")
    print(f"Title: {paper['title'][:80]}")

    # --- Abstract translation ---
    abstract_cache = DATA_DIR / date_str / arxiv_id / "abstract_zh.txt"
    if abstract_cache.exists():
        paper["abstract_zh"] = abstract_cache.read_text(encoding="utf-8")
    else:
        print(f"[main] Translating abstract...")
        try:
            paper["abstract_zh"] = translate_abstract(paper["abstract"])
            abstract_cache.parent.mkdir(parents=True, exist_ok=True)
            abstract_cache.write_text(paper["abstract_zh"], encoding="utf-8")
        except Exception as e:
            print(f"[main] Abstract translation failed: {e}")
            paper["abstract_zh"] = ""

    # --- Title translation ---
    title_cache = DATA_DIR / date_str / arxiv_id / "title_zh.txt"
    if title_cache.exists():
        paper["title_zh"] = title_cache.read_text(encoding="utf-8")
    else:
        print(f"[main] Translating title...")
        try:
            from .translate import _client, TRANSLATE_MODEL
            msg = _client.messages.create(
                model=TRANSLATE_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": f"請將以下論文標題翻譯成繁體中文（保留英文縮寫和專有名詞），只回覆翻譯結果：\n\n{paper['title']}"}],
            )
            paper["title_zh"] = msg.content[0].text.strip()
            title_cache.parent.mkdir(parents=True, exist_ok=True)
            title_cache.write_text(paper["title_zh"], encoding="utf-8")
        except Exception as e:
            print(f"[main] Title translation failed: {e}")
            paper["title_zh"] = ""

    # --- Metadata tags ---
    print(f"[main] Generating tags...")
    try:
        paper["tags"] = generate_tags(paper["title"], paper["abstract"], arxiv_id, date_str)
    except Exception as e:
        print(f"[main] Tag generation failed: {e}")
        paper["tags"] = {"domain": [], "method": [], "task": [], "dataset": [], "open_source": False}

    # --- PDF download ---
    pdf_path = download_pdf(arxiv_id, date_str)
    if pdf_path is None:
        print(f"[main] Skipping full translation (PDF unavailable)")
        paper["content"] = []
        return paper

    # --- PDF parse ---
    print(f"[main] Parsing PDF...")
    try:
        elements = parse_pdf(pdf_path, arxiv_id, date_str)
    except Exception as e:
        print(f"[main] PDF parse failed: {e}")
        paper["content"] = []
        return paper

    # --- Full translation ---
    print(f"[main] Translating full content ({len(elements)} elements)...")
    try:
        paper["content"] = translate_paper_content(elements, arxiv_id, date_str)
    except Exception as e:
        print(f"[main] Full translation failed: {e}")
        paper["content"] = elements  # fallback: untranslated

    return paper


def run(target_date: date | None = None) -> None:
    if target_date is None:
        target_date = date.today()
    date_str = target_date.isoformat()
    print(f"\n{'#'*60}")
    print(f"HF Papers pipeline — {date_str}")
    print(f"{'#'*60}\n")

    # 1. Fetch paper list
    papers = fetch_daily_papers(target_date)
    if not papers:
        print(f"[main] No papers found for {date_str}, exiting")
        return

    # 2. Process each paper
    enriched_papers = []
    for paper in papers:
        try:
            enriched = process_paper(paper, date_str)
            enriched_papers.append(enriched)
        except Exception as e:
            print(f"[main] ERROR processing {paper.get('arxiv_id', '?')}: {e}")
            enriched_papers.append(paper)  # include with whatever we have

    # 3. Build site
    print(f"\n[main] Building site...")
    build_site(date_str, enriched_papers)

    # 4. Send email
    print(f"\n[main] Sending email digest...")
    try:
        send_daily_digest(date_str, enriched_papers)
    except Exception as e:
        print(f"[main] Email failed (non-fatal): {e}")

    print(f"\n[main] Done! Processed {len(enriched_papers)} papers for {date_str}")


if __name__ == "__main__":
    # Allow passing a date as CLI argument: python -m src.main 2026-02-25
    target = None
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    run(target)
