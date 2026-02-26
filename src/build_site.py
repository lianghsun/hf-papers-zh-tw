"""Generate static HTML site from processed paper data."""
import json
import shutil
from pathlib import Path
from datetime import date, timedelta

from jinja2 import Environment, FileSystemLoader

from .config import DATA_DIR, DOCS_DIR, TEMPLATES_DIR, SITE_TITLE

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)


def _base_path(depth: int) -> str:
    """Return relative path to site root given directory depth."""
    return "../" * depth if depth > 0 else "./"


def _copy_figures(date_str: str, arxiv_id: str) -> None:
    src = DATA_DIR / date_str / arxiv_id / "figures"
    dst = DOCS_DIR / "figures" / date_str / arxiv_id
    if src.exists():
        dst.mkdir(parents=True, exist_ok=True)
        for fig in src.iterdir():
            shutil.copy2(fig, dst / fig.name)


def build_paper_page(paper: dict, date_str: str) -> None:
    arxiv_id = paper["arxiv_id"]
    out_dir = DOCS_DIR / "paper" / arxiv_id
    out_dir.mkdir(parents=True, exist_ok=True)

    _copy_figures(date_str, arxiv_id)

    tmpl = jinja_env.get_template("paper.html")
    html = tmpl.render(
        paper=paper,
        date=date_str,
        site_title=SITE_TITLE,
        base_path=_base_path(2),  # paper/{id}/index.html → 2 levels up
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def build_daily_index(date_str: str, papers: list[dict]) -> None:
    out_dir = DOCS_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine prev/next date links
    d = date.fromisoformat(date_str)
    prev_str = (d - timedelta(days=1)).isoformat()
    next_str = (d + timedelta(days=1)).isoformat()
    prev_date = prev_str if (DOCS_DIR / prev_str / "index.html").exists() else None
    next_date = next_str if (DOCS_DIR / next_str / "index.html").exists() else None

    tmpl = jinja_env.get_template("daily_index.html")
    html = tmpl.render(
        date=date_str,
        papers=papers,
        prev_date=prev_date,
        next_date=next_date,
        site_title=SITE_TITLE,
        base_path=_base_path(1),  # {date}/index.html → 1 level up
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def build_home_index() -> None:
    # Collect all dates that have a daily index page
    dates = sorted(
        [d.name for d in DOCS_DIR.iterdir()
         if d.is_dir() and (d / "index.html").exists()
         and len(d.name) == 10 and d.name[4] == "-"],
        reverse=True,
    )

    entries = []
    for d in dates[:60]:  # show last 60 days
        papers_cache = DATA_DIR / d / "papers.json"
        count = 0
        if papers_cache.exists():
            try:
                count = len(json.loads(papers_cache.read_text()))
            except Exception:
                pass
        entries.append({"date": d, "path": f"{d}/index.html", "count": count})

    tmpl = jinja_env.get_template("index.html")
    html = tmpl.render(
        dates=entries,
        site_title=SITE_TITLE,
        base_path=_base_path(0),
    )
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def build_site(date_str: str, papers: list[dict]) -> None:
    """Build all pages for a given date."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[build] Building daily index for {date_str}")
    build_daily_index(date_str, papers)

    for paper in papers:
        print(f"[build] Building paper page: {paper['arxiv_id']}")
        build_paper_page(paper, date_str)

    print("[build] Rebuilding home index")
    build_home_index()
