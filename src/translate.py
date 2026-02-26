"""Translate paper Markdown content using Claude API."""
import re
import json
import anthropic

from .config import ANTHROPIC_API_KEY, TRANSLATE_MODEL, DATA_DIR

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = (
    "你是一位專業的學術論文翻譯專家，專門翻譯人工智慧和機器學習領域的論文。\n"
    "翻譯規則：\n"
    "1. 翻譯成繁體中文（台灣用語）\n"
    "2. 專有名詞、模型名稱、縮寫保留英文（如 Transformer、RLHF、LoRA、ResNet）\n"
    "3. 保持學術文章的嚴謹語氣，不省略任何內容\n"
    "4. 保留所有 Markdown 格式符號（#、**、*、|、-）\n"
    "5. 表格的 Markdown 格式（| col | col |）完整保留，只翻譯文字內容\n"
    "6. 方括號標記如 [FIGURE:xxx]、[FIGURE_CAPTION] 保留原樣不翻譯\n"
    "7. LaTeX 數學式（$...$ 或 $$...$$）保留原樣\n"
    "8. 不要自行新增任何方括號標記，只翻譯文字內容"
)


def translate_abstract(abstract: str) -> str:
    msg = _client.messages.create(
        model=TRANSLATE_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"請翻譯以下論文摘要：\n\n{abstract}"}],
    )
    return msg.content[0].text.strip()


def translate_title(title: str) -> str:
    msg = _client.messages.create(
        model=TRANSLATE_MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content":
            f"請將以下論文標題翻譯成繁體中文（保留英文縮寫和專有名詞），只回覆翻譯結果：\n\n{title}"}],
    )
    return msg.content[0].text.strip()


def _split_markdown(markdown: str, max_chars: int = 3000) -> list[str]:
    """
    Split Markdown into chunks at section boundaries (# headers).
    If a section is still too large, further split by paragraphs.
    """
    # Split at top-level section headers
    parts = re.split(r"(?m)^(?=#{1,3} )", markdown)
    chunks = []
    current = ""

    for part in parts:
        if len(current) + len(part) > max_chars and current:
            chunks.append(current.strip())
            current = part
        else:
            current += part

    if current.strip():
        # Further split large chunks by paragraphs
        if len(current) > max_chars:
            paras = current.split("\n\n")
            sub = ""
            for p in paras:
                if len(sub) + len(p) > max_chars and sub:
                    chunks.append(sub.strip())
                    sub = p
                else:
                    sub += "\n\n" + p
            if sub.strip():
                chunks.append(sub.strip())
        else:
            chunks.append(current.strip())

    return [c for c in chunks if c]


def translate_markdown(markdown: str, arxiv_id: str, date_str: str) -> str:
    """
    Translate full paper Markdown, chunked by sections.
    Results are cached.
    """
    cache_path = DATA_DIR / date_str / arxiv_id / "translated_md.txt"
    if cache_path.exists():
        print(f"[translate] Using cache for {arxiv_id}")
        return cache_path.read_text(encoding="utf-8")

    chunks = _split_markdown(markdown)
    print(f"[translate] {arxiv_id}: {len(chunks)} chunks to translate")

    translated_chunks = []
    for i, chunk in enumerate(chunks):
        print(f"[translate] {arxiv_id} chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
        try:
            msg = _client.messages.create(
                model=TRANSLATE_MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content":
                    f"請翻譯以下論文段落（保留所有 Markdown 格式）：\n\n{chunk}"}],
            )
            translated_chunks.append(msg.content[0].text.strip())
        except Exception as e:
            print(f"[translate] Chunk {i+1} failed: {e}, using original")
            translated_chunks.append(chunk)

    result = "\n\n".join(translated_chunks)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(result, encoding="utf-8")
    return result
