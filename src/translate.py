"""Translate paper content using Claude API."""
import re
import json
import anthropic
from pathlib import Path

from .config import ANTHROPIC_API_KEY, TRANSLATE_MODEL, DATA_DIR

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = (
    "你是一位專業的學術論文翻譯專家，專門翻譯人工智慧和機器學習領域的論文。\n"
    "翻譯規則：\n"
    "1. 翻譯成繁體中文（台灣用語）\n"
    "2. 專有名詞、模型名稱、縮寫保留英文（如 Transformer、RLHF、LoRA、ResNet）\n"
    "3. 保持學術文章的嚴謹語氣\n"
    "4. 不省略任何內容，完整翻譯\n"
    "5. 如果輸入包含 HTML 表格標籤，保留 HTML 結構只翻譯文字\n"
    "6. LaTeX 公式保持原樣，只翻譯周圍的說明文字"
)

SEP = "|||SEG|||"


def translate_abstract(abstract: str) -> str:
    msg = _client.messages.create(
        model=TRANSLATE_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"請翻譯以下論文摘要：\n\n{abstract}"}],
    )
    return msg.content[0].text.strip()


def translate_paper_content(elements: list[dict], arxiv_id: str, date_str: str) -> list[dict]:
    """
    Translate all text elements in place, adding 'text_zh' field.
    Non-text elements (image, formula) pass through unchanged.
    Results are cached.
    """
    cache_path = DATA_DIR / date_str / arxiv_id / "translated.json"
    if cache_path.exists():
        print(f"[translate] Using cache for {arxiv_id}")
        return json.loads(cache_path.read_text())

    result = [dict(e) for e in elements]  # shallow copy

    # Collect indices of translatable text elements
    translatable_types = {"text", "section", "title", "caption", "footnote"}
    text_indices = [i for i, e in enumerate(result) if e["type"] in translatable_types]

    # Process in batches (by accumulated character length)
    batch_indices: list[int] = []
    batch_chars = 0
    BATCH_LIMIT = 3000

    def flush_batch():
        if not batch_indices:
            return
        texts = [result[i]["text"] for i in batch_indices]
        translations = _translate_batch(texts)
        for idx, trans in zip(batch_indices, translations):
            result[idx]["text_zh"] = trans

    for i in text_indices:
        text_len = len(result[i]["text"])
        if batch_chars + text_len > BATCH_LIMIT and batch_indices:
            flush_batch()
            batch_indices = []
            batch_chars = 0
        batch_indices.append(i)
        batch_chars += text_len

    flush_batch()

    # Translate tables separately (keep HTML structure)
    for i, elem in enumerate(result):
        if elem["type"] == "table":
            try:
                msg = _client.messages.create(
                    model=TRANSLATE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": (
                            "請翻譯以下 HTML 表格的文字內容，完整保留所有 HTML 標籤和結構：\n\n"
                            + elem["text"]
                        ),
                    }],
                )
                result[i]["text_zh"] = msg.content[0].text.strip()
            except Exception as e:
                print(f"[translate] Table translation failed: {e}")
                result[i]["text_zh"] = elem["text"]  # fallback: original

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[translate] {arxiv_id}: translated {len(text_indices)} text elements")
    return result


def _translate_batch(texts: list[str]) -> list[str]:
    """Translate a batch of strings, returning same-length list of translations."""
    if not texts:
        return []

    # Join with unique separator
    combined = f"\n{SEP}\n".join(texts)
    prompt = (
        f"請翻譯以下 {len(texts)} 段文字。"
        f"每段之間以 {SEP} 分隔，請保持完全相同的分隔格式回覆翻譯結果：\n\n"
        + combined
    )

    msg = _client.messages.create(
        model=TRANSLATE_MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    content = msg.content[0].text

    parts = [p.strip() for p in content.split(SEP)]

    # Ensure we return exactly len(texts) items
    if len(parts) < len(texts):
        # Pad with originals for any missing translations
        parts += texts[len(parts):]
    return parts[: len(texts)]
