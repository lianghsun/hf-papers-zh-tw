"""Parse PDF pages using PyMuPDF (page rendering) + DotsOCR (layout understanding)."""
import io
import json
import base64
import re
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from openai import OpenAI

from .config import DOTSOCR_ENDPOINT, DOTSOCR_API_KEY, DOTSOCR_MODEL, DATA_DIR

CATEGORY_TYPE_MAP = {
    "Title": "title",
    "Section-header": "section",
    "Text": "text",
    "Table": "table",
    "Formula": "formula",
    "Caption": "caption",
    "Footnote": "footnote",
    "List-item": "text",
    "Page-header": None,   # skip
    "Page-footer": None,   # skip
    "Picture": "image",
}


def _render_page(page: fitz.Page, scale: float = 2.0) -> bytes:
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def _crop_image(page_png: bytes, bbox: list) -> bytes:
    img = Image.open(io.BytesIO(page_png))
    x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
    # Clamp to image bounds
    w, h = img.size
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return page_png  # fallback: return full page
    cropped = img.crop((x1, y1, x2, y2))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _call_dotsocr(page_png: bytes, client: OpenAI) -> list[dict]:
    b64 = base64.b64encode(page_png).decode()
    response = client.chat.completions.create(
        model=DOTSOCR_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "prompt_layout_all_en"},
            ],
        }],
        max_tokens=24000,
    )
    raw = response.choices[0].message.content

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "elements" in parsed:
            return parsed["elements"]
        return []
    except json.JSONDecodeError:
        # Last resort: find JSON array
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return []


def _fallback_parse_page(page: fitz.Page, page_num: int) -> list[dict]:
    """Use PyMuPDF text blocks when DotsOCR fails."""
    blocks = page.get_text("blocks")
    elements = []
    for block in blocks:
        if block[6] == 0:  # text block
            text = block[4].strip()
            if text:
                elements.append({
                    "category": "Text",
                    "bbox": list(block[:4]),
                    "text": text,
                })
    return elements


def parse_pdf(pdf_path: Path, arxiv_id: str, date_str: str) -> list[dict]:
    """
    Parse a PDF and return structured content elements.
    Results are cached; re-run is skipped if cache exists.
    """
    cache_path = DATA_DIR / date_str / arxiv_id / "parsed.json"
    if cache_path.exists():
        print(f"[parse] Using cache for {arxiv_id}")
        return json.loads(cache_path.read_text())

    figures_dir = DATA_DIR / date_str / arxiv_id / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    client = OpenAI(base_url=DOTSOCR_ENDPOINT, api_key=DOTSOCR_API_KEY)
    doc = fitz.open(str(pdf_path))

    all_elements: list[dict] = []
    fig_count = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_png = _render_page(page)
        print(f"[parse] {arxiv_id} page {page_num + 1}/{len(doc)}")

        try:
            raw_elements = _call_dotsocr(page_png, client)
        except Exception as e:
            print(f"[parse] DotsOCR failed page {page_num + 1}: {e}, using fallback")
            raw_elements = _fallback_parse_page(page, page_num)

        for elem in raw_elements:
            if not isinstance(elem, dict):
                continue  # skip malformed elements (e.g. int) from DotsOCR
            category = elem.get("category", "Text")
            elem_type = CATEGORY_TYPE_MAP.get(category)
            bbox = elem.get("bbox", [])

            if elem_type is None:
                continue  # skip headers/footers

            if elem_type == "image":
                if not bbox:
                    continue
                fig_count += 1
                fig_name = f"p{page_num + 1}_fig{fig_count}.png"
                fig_path = figures_dir / fig_name
                try:
                    fig_bytes = _crop_image(page_png, bbox)
                    fig_path.write_bytes(fig_bytes)
                    all_elements.append({
                        "type": "image",
                        "fig_name": fig_name,
                        "page": page_num + 1,
                    })
                except Exception as e:
                    print(f"[parse] Figure crop failed: {e}")
            else:
                text = elem.get("text", "").strip()
                if not text:
                    continue
                all_elements.append({
                    "type": elem_type,
                    "text": text,
                    "page": page_num + 1,
                })

    doc.close()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(all_elements, ensure_ascii=False, indent=2))
    print(f"[parse] {arxiv_id}: {len(all_elements)} elements, {fig_count} figures")
    return all_elements
