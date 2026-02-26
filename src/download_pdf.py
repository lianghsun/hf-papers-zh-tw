"""Download PDF from arxiv."""
import time
import httpx
from pathlib import Path
from .config import DATA_DIR

ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HFPapersBot/1.0)"
}


def download_pdf(arxiv_id: str, date_str: str) -> Path | None:
    """Download arxiv PDF and return local path. Returns None on failure."""
    pdf_dir = DATA_DIR / date_str / "pdfs"
    pdf_path = pdf_dir / f"{arxiv_id}.pdf"

    if pdf_path.exists() and pdf_path.stat().st_size > 1024:
        return pdf_path

    pdf_dir.mkdir(parents=True, exist_ok=True)
    url = ARXIV_PDF_URL.format(arxiv_id=arxiv_id)
    print(f"[pdf] Downloading {arxiv_id}...")

    try:
        with httpx.Client(follow_redirects=True, timeout=60, headers=HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            if "application/pdf" not in resp.headers.get("content-type", ""):
                print(f"[pdf] WARNING: unexpected content-type for {arxiv_id}")
            pdf_path.write_bytes(resp.content)
        print(f"[pdf] Saved {arxiv_id} ({pdf_path.stat().st_size // 1024} KB)")
        time.sleep(1)  # be polite to arxiv
        return pdf_path
    except Exception as e:
        print(f"[pdf] FAILED {arxiv_id}: {e}")
        return None
