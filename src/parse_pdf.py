"""Parse PDF using DotsOCR (returns Markdown per page) + PyMuPDF for figures."""
import json
import base64
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF
from openai import OpenAI

from .config import DOTSOCR_ENDPOINT, DOTSOCR_API_KEY, DOTSOCR_MODEL, DATA_DIR


def _render_page(page: fitz.Page, scale: float = 2.0) -> bytes:
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def _call_dotsocr(png_bytes: bytes, client: OpenAI) -> str:
    """Call DotsOCR and return Markdown text for one page."""
    b64 = base64.b64encode(png_bytes).decode()
    resp = client.chat.completions.create(
        model=DOTSOCR_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": "prompt_layout_all_en"},
        ]}],
        max_tokens=24000,
    )
    return resp.choices[0].message.content.strip()


def _extract_figures_pymupdf(doc: fitz.Document, figures_dir: Path) -> list[dict]:
    """Extract embedded images from PDF using PyMuPDF."""
    figures = []
    fig_count = 0
    seen_xrefs = set()

    for page_num in range(len(doc)):
        page = doc[page_num]
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                base_img = doc.extract_image(xref)
                img_bytes = base_img["image"]
                ext = base_img["ext"]
                if len(img_bytes) < 2048:  # skip tiny icons
                    continue
                fig_count += 1
                fig_name = f"fig{fig_count}.{ext}"
                (figures_dir / fig_name).write_bytes(img_bytes)
                figures.append({"name": fig_name, "caption": ""})
            except Exception:
                pass

    return figures


def parse_pdf(pdf_path: Path, arxiv_id: str, date_str: str) -> dict:
    """
    Parse PDF with DotsOCR (Markdown per page) + PyMuPDF figure extraction.
    Returns {"source": "pdf", "markdown": str, "figures": [...]}
    """
    cache_path = DATA_DIR / date_str / arxiv_id / "parsed_pdf.json"
    if cache_path.exists():
        print(f"[pdf_parse] Using cache for {arxiv_id}")
        return json.loads(cache_path.read_text())

    figures_dir = DATA_DIR / date_str / arxiv_id / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    client = OpenAI(base_url=DOTSOCR_ENDPOINT, api_key=DOTSOCR_API_KEY)
    doc = fitz.open(str(pdf_path))
    n_pages = len(doc)
    print(f"[pdf_parse] {arxiv_id}: {n_pages} pages")

    # Render all pages upfront
    page_pngs = []
    for i in range(n_pages):
        page_pngs.append(_render_page(doc[i]))

    # Call DotsOCR in parallel (up to 4 concurrent)
    page_markdowns = [""] * n_pages

    def process_page(args):
        idx, png = args
        try:
            md = _call_dotsocr(png, client)
            print(f"[pdf_parse] {arxiv_id} page {idx+1}/{n_pages} ✓ ({len(md)} chars)")
            return idx, md
        except Exception as e:
            print(f"[pdf_parse] {arxiv_id} page {idx+1} DotsOCR failed: {e}")
            # Fallback: extract text with PyMuPDF
            page = doc[idx]
            return idx, page.get_text("text").strip()

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(process_page, (i, png)): i for i, png in enumerate(page_pngs)}
        for future in as_completed(futures):
            idx, md = future.result()
            page_markdowns[idx] = md

    # Extract figures with PyMuPDF
    figures = _extract_figures_pymupdf(doc, figures_dir)
    doc.close()

    # Combine all page Markdowns
    markdown = "\n\n---\n\n".join(md for md in page_markdowns if md)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    result = {"source": "pdf", "markdown": markdown, "figures": figures}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[pdf_parse] {arxiv_id}: {len(markdown)} chars, {len(figures)} figures")
    return result
