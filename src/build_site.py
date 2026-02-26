"""Generate static HTML site from processed paper data."""
import json
import shutil
import re
from pathlib import Path
from datetime import date, timedelta

import markdown as md_lib
from jinja2 import Environment, FileSystemLoader

from .config import DATA_DIR, DOCS_DIR, TEMPLATES_DIR, SITE_TITLE

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)

_md = md_lib.Markdown(extensions=["tables", "fenced_code", "toc"])


def _render_markdown(text: str) -> str:
    """Convert Markdown to HTML, also embed figure placeholders."""
    _md.reset()
    html = _md.convert(text)
    return html


def _base_path(depth: int) -> str:
    return "../" * depth if depth > 0 else "./"


def _copy_figures(date_str: str, arxiv_id: str) -> None:
    src = DATA_DIR / date_str / arxiv_id / "figures"
    dst = DOCS_DIR / "figures" / date_str / arxiv_id
    if src.exists():
        dst.mkdir(parents=True, exist_ok=True)
        for fig in src.iterdir():
            shutil.copy2(fig, dst / fig.name)


def _insert_pdf_figures_inline(content_html: str, figures: list[dict], figures_base: str) -> str:
    """
    Insert PDF figures inline at the position of their captions in the HTML.
    Looks for <p> tags starting with 'Figure N.' or '圖 N.' and inserts
    the corresponding figN.png image immediately before each caption paragraph.
    Falls back to appending remaining figures at the end if no caption found.
    """
    # Build map: figure_number -> filename  (e.g. {1: "fig1.png", 2: "fig2.png"})
    fig_map: dict[int, str] = {}
    for fig in figures:
        m = re.match(r"fig(\d+)\.", fig["name"], re.IGNORECASE)
        if m:
            fig_map[int(m.group(1))] = fig["name"]

    if not fig_map:
        return content_html

    inserted = set()

    def _replace_caption(match: re.Match) -> str:
        full_tag = match.group(0)
        n = int(match.group(1))
        fname = fig_map.get(n)
        if fname and n not in inserted:
            inserted.add(n)
            img = (
                f'<figure class="paper-figure">'
                f'<img src="{figures_base}{fname}" loading="lazy" alt="Figure {n}">'
                f'</figure>\n'
            )
            return img + full_tag
        return full_tag

    # Match <p> starting with Figure N. / 圖 N.
    # Handles both plain and <strong>-wrapped captions, e.g.:
    #   <p>圖 2. ...          → plain
    #   <p><strong>圖 1.</strong>  → bold with closing tag after period
    pattern = re.compile(
        r'<p>(?:<strong>)?(?:Figure|Fig\.?|圖)\s+(\d+)\.?(?:</strong>)?',
        re.IGNORECASE,
    )
    content_html = pattern.sub(_replace_caption, content_html)

    # Append any figures whose captions were not found in the text
    missing = [fig_map[n] for n in sorted(fig_map) if n not in inserted]
    if missing:
        content_html += '<hr><h2>圖表</h2><div class="figures-gallery">'
        for fname in missing:
            content_html += (
                f'<figure class="paper-figure">'
                f'<img src="{figures_base}{fname}" loading="lazy" alt="{fname}">'
                f'</figure>'
            )
        content_html += '</div>'

    return content_html


def build_paper_page(paper: dict, date_str: str) -> None:
    arxiv_id = paper["arxiv_id"]
    out_dir = DOCS_DIR / "paper" / arxiv_id
    out_dir.mkdir(parents=True, exist_ok=True)

    _copy_figures(date_str, arxiv_id)

    # Convert Markdown to HTML
    content_html = ""
    figures_base = f"../../figures/{date_str}/{arxiv_id}/"
    if paper.get("content_md_zh"):
        md_text = paper["content_md_zh"]
        # Remove any fake [FIGURE:N] markers Claude may have introduced (PDF path artifact)
        md_text = re.sub(r"\[FIGURE:\d+\]\s*", "", md_text)
        # Clean up [FIGURE_CAPTION] markers → just the caption text
        md_text = re.sub(r"\[FIGURE_CAPTION\]\s*", "", md_text)

        content_html = _render_markdown(md_text)

        # Replace proper [FIGURE:filename] placeholders (HTML path only)
        content_html = re.sub(
            r"\[FIGURE:([^\]]+\.(png|jpg|jpeg|svg|gif))\]",
            lambda m: f'<figure class="paper-figure"><img src="{figures_base}{m.group(1)}" loading="lazy"></figure>',
            content_html
        )

    # For PDF-parsed papers: insert figures inline at their natural reading position
    if paper.get("parse_source") == "pdf" and paper.get("figures"):
        content_html = _insert_pdf_figures_inline(content_html, paper["figures"], figures_base)

    tmpl = jinja_env.get_template("paper.html")
    html = tmpl.render(
        paper=paper,
        content_html=content_html,
        date=date_str,
        site_title=SITE_TITLE,
        base_path=_base_path(2),
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def build_daily_index(date_str: str, papers: list[dict]) -> None:
    out_dir = DOCS_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

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
        base_path=_base_path(1),
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def build_home_index() -> None:
    dates = sorted(
        [d.name for d in DOCS_DIR.iterdir()
         if d.is_dir() and (d / "index.html").exists()
         and len(d.name) == 10 and d.name[4] == "-"],
        reverse=True,
    )
    entries = []
    for d in dates[:60]:
        count = 0
        papers_cache = DATA_DIR / d / "papers.json"
        if papers_cache.exists():
            try:
                count = len(json.loads(papers_cache.read_text()))
            except Exception:
                pass
        entries.append({"date": d, "path": f"{d}/index.html", "count": count})

    tmpl = jinja_env.get_template("index.html")
    html = tmpl.render(dates=entries, site_title=SITE_TITLE, base_path=_base_path(0))
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def build_site(date_str: str, papers: list[dict]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[build] Daily index for {date_str}")
    build_daily_index(date_str, papers)
    for paper in papers:
        print(f"[build] Paper: {paper['arxiv_id']}")
        build_paper_page(paper, date_str)
    print("[build] Home index")
    build_home_index()
