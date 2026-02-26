"""Parse arxiv HTML version of a paper into Markdown + figure list."""
import httpx
import re
from pathlib import Path
from bs4 import BeautifulSoup, Tag

from .config import DATA_DIR

ARXIV_HTML_URL = "https://arxiv.org/html/{arxiv_id}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HFPapersBot/1.0)"}


def _has_html_version(arxiv_id: str) -> bool:
    try:
        r = httpx.head(ARXIV_HTML_URL.format(arxiv_id=arxiv_id),
                       follow_redirects=True, timeout=10, headers=HEADERS)
        return r.status_code == 200
    except Exception:
        return False


def _elem_to_md(elem: Tag) -> str:
    """Convert a single BS4 element to Markdown."""
    name = elem.name
    text = elem.get_text(" ", strip=True)
    if not text:
        return ""
    if name == "h1":
        return f"# {text}"
    if name == "h2":
        return f"## {text}"
    if name == "h3":
        return f"### {text}"
    if name == "h4":
        return f"#### {text}"
    if name == "p":
        return text
    if name in ("ul", "ol"):
        items = [f"- {li.get_text(' ', strip=True)}" for li in elem.find_all("li")]
        return "\n".join(items)
    if name == "table":
        return _table_to_md(elem)
    return text


def _table_to_md(table: Tag) -> str:
    """Convert HTML table to Markdown table."""
    rows = table.find_all("tr")
    if not rows:
        return ""
    lines = []
    for i, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        line = "| " + " | ".join(c.get_text(" ", strip=True) for c in cells) + " |"
        lines.append(line)
        if i == 0:
            sep = "| " + " | ".join("---" for _ in cells) + " |"
            lines.append(sep)
    return "\n".join(lines)


def _download_figure(url: str, dest: Path) -> bool:
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True, headers=HEADERS)
        if r.status_code == 200 and len(r.content) > 500:
            dest.write_bytes(r.content)
            return True
    except Exception:
        pass
    return False


def parse_arxiv_html(arxiv_id: str, date_str: str) -> dict | None:
    """
    Fetch and parse arxiv HTML version.
    Returns {"markdown": str, "figures": [{"name": str, "caption": str}]}
    or None if HTML version doesn't exist.
    """
    cache_path = DATA_DIR / date_str / arxiv_id / "parsed_html.json"
    if cache_path.exists():
        import json
        print(f"[html] Using cache for {arxiv_id}")
        return json.loads(cache_path.read_text())

    url = ARXIV_HTML_URL.format(arxiv_id=arxiv_id)
    print(f"[html] Fetching {url}")
    try:
        r = httpx.get(url, follow_redirects=True, timeout=30, headers=HEADERS)
    except Exception as e:
        print(f"[html] Fetch failed: {e}")
        return None

    if r.status_code != 200:
        print(f"[html] HTTP {r.status_code} — no HTML version")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Remove nav, scripts, styles, references section
    for tag in soup.find_all(["script", "style", "nav", "footer"]):
        tag.decompose()

    # Try to find main article body
    article = soup.find("article") or soup.find("div", class_="ltx_document") or soup.body
    if not article:
        return None

    # --- Extract figures ---
    figures_dir = DATA_DIR / date_str / arxiv_id / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    figures = []
    base_url = f"https://arxiv.org/html/{arxiv_id}/"

    for fig in article.find_all("figure"):
        img = fig.find("img")
        cap = fig.find("figcaption")
        caption_text = cap.get_text(" ", strip=True) if cap else ""

        if img and img.get("src"):
            src = img["src"]
            if not src.startswith("http"):
                src = base_url + src.lstrip("/")
            fig_name = re.sub(r"[^a-zA-Z0-9._-]", "_", img["src"].split("/")[-1])
            if not fig_name.endswith((".png", ".jpg", ".jpeg", ".svg", ".gif")):
                fig_name += ".png"
            dest = figures_dir / fig_name
            ok = _download_figure(src, dest)
            if ok:
                figures.append({"name": fig_name, "caption": caption_text})
            # Replace figure with a placeholder marker in the HTML
            fig.replace_with(soup.new_tag("p",
                string=f"[FIGURE:{fig_name}] {caption_text}"))
        elif caption_text:
            fig.replace_with(soup.new_tag("p", string=f"[FIGURE_CAPTION] {caption_text}"))
        else:
            fig.decompose()

    # --- Build Markdown ---
    md_parts = []
    skip_tags = {"script", "style", "nav", "footer", "aside"}
    block_tags = {"h1", "h2", "h3", "h4", "h5", "p", "ul", "ol", "table", "pre", "blockquote"}

    for elem in article.descendants:
        if not isinstance(elem, Tag):
            continue
        if elem.name in skip_tags:
            continue
        if elem.name in block_tags:
            # Only process top-level blocks (not nested)
            if elem.parent and elem.parent.name in block_tags - {"ul", "ol"}:
                continue
            md = _elem_to_md(elem)
            if md:
                md_parts.append(md)

    markdown = "\n\n".join(md_parts)
    # Clean up excessive whitespace
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    result = {"source": "html", "markdown": markdown, "figures": figures}
    import json
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[html] {arxiv_id}: {len(markdown)} chars, {len(figures)} figures")
    return result
