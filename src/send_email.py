"""Send daily digest email via Gmail SMTP."""
import smtplib
from email.message import EmailMessage

from .config import GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_TO, SITE_BASE_URL


def _build_html(date_str: str, papers: list[dict]) -> str:
    rows = []
    for p in papers:
        arxiv_id = p["arxiv_id"]
        title = p.get("title_zh") or p["title"]
        title_en = p["title"] if p.get("title_zh") else ""
        abstract = p.get("abstract_zh") or p.get("abstract", "")
        # Truncate abstract to ~150 chars
        short_abstract = abstract[:200] + "…" if len(abstract) > 200 else abstract
        tags = p.get("tags", {})
        all_tags = (
            [f'<span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:999px;font-size:12px;">{t}</span>' for t in tags.get("domain", [])]
            + [f'<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:999px;font-size:12px;">{t}</span>' for t in tags.get("method", [])]
        )
        tags_html = " ".join(all_tags[:5])  # limit to 5 tags in email

        site_url = f"{SITE_BASE_URL}/paper/{arxiv_id}/"
        arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"

        rows.append(f"""
<div style="border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px;margin-bottom:16px;font-family:sans-serif;">
  <div style="font-size:12px;color:#6b7280;margin-bottom:4px;">{arxiv_id}</div>
  <div style="font-size:16px;font-weight:600;margin-bottom:4px;">
    <a href="{site_url}" style="color:#111827;text-decoration:none;">{title}</a>
  </div>
  {"<div style='font-size:13px;color:#6b7280;margin-bottom:8px;'>" + title_en + "</div>" if title_en else ""}
  <div style="font-size:14px;color:#374151;margin-bottom:10px;line-height:1.6;">{short_abstract}</div>
  <div style="margin-bottom:10px;">{tags_html}</div>
  <div style="font-size:13px;">
    <a href="{site_url}" style="color:#2563eb;margin-right:12px;">繁中全文 →</a>
    <a href="{arxiv_url}" style="color:#6b7280;">arXiv</a>
  </div>
</div>""")

    papers_html = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html>
<body style="max-width:700px;margin:0 auto;padding:24px;font-family:sans-serif;background:#fafafa;">
  <div style="margin-bottom:24px;padding-bottom:16px;border-bottom:2px solid #e5e7eb;">
    <h1 style="font-size:22px;font-weight:700;margin:0 0 4px;">📄 HF Papers 繁中 — {date_str}</h1>
    <p style="color:#6b7280;margin:0;">今日共 {len(papers)} 篇論文
    　<a href="{SITE_BASE_URL}/{date_str}/" style="color:#2563eb;">查看完整頁面 →</a></p>
  </div>
  {papers_html}
  <div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af;text-align:center;">
    <a href="{SITE_BASE_URL}" style="color:#6b7280;">{SITE_BASE_URL}</a>
  </div>
</body>
</html>"""


def send_daily_digest(date_str: str, papers: list[dict]) -> None:
    if not papers:
        print("[email] No papers, skipping email")
        return

    html_body = _build_html(date_str, papers)

    msg = EmailMessage()
    msg["Subject"] = f"[HF Papers] {date_str} 今日 {len(papers)} 篇論文"
    msg["From"] = GMAIL_USER
    msg["To"] = EMAIL_TO
    msg.set_content(f"今日 {len(papers)} 篇論文：{SITE_BASE_URL}/{date_str}/")  # plaintext fallback
    msg.add_alternative(html_body, subtype="html")

    print(f"[email] Sending digest to {EMAIL_TO}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)
    print("[email] Sent successfully")
