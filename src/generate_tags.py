"""Generate metadata tags for a paper using Claude."""
import re
import json
import anthropic

from .config import ANTHROPIC_API_KEY, TRANSLATE_MODEL, DATA_DIR

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

TAG_PROMPT = """\
分析以下論文，生成結構化分類標籤，**只回覆 JSON，不要任何其他文字**：

標題：{title}
摘要：{abstract}

請回覆以下格式：
{{
  "domain": [],
  "method": [],
  "task": [],
  "dataset": [],
  "open_source": false
}}

說明：
- domain: 研究領域，從以下選擇（可多選）：NLP、CV、RL、Multimodal、Audio、Robotics、Theory、Graph、Medical、Code、Other
- method: 主要使用的方法/技術（例如：Transformer、Diffusion、RLHF、RAG、LoRA、Mamba、SSM、GNN）
- task: 應用任務（例如：Text Generation、Image Classification、Object Detection、QA、Summarization）
- dataset: 論文中使用或提出的資料集名稱，沒有則填空陣列
- open_source: 論文是否提及公開 code、model 或 dataset（true/false）
"""


def generate_tags(title: str, abstract: str, arxiv_id: str, date_str: str) -> dict:
    """Generate and cache metadata tags for a paper."""
    cache_path = DATA_DIR / date_str / arxiv_id / "tags.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    prompt = TAG_PROMPT.format(title=title, abstract=abstract)
    msg = _client.messages.create(
        model=TRANSLATE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    content = msg.content[0].text.strip()

    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        tags = json.loads(match.group() if match else content)
    except Exception:
        tags = {
            "domain": [],
            "method": [],
            "task": [],
            "dataset": [],
            "open_source": False,
        }

    # Normalize
    for key in ("domain", "method", "task", "dataset"):
        if not isinstance(tags.get(key), list):
            tags[key] = []
    if not isinstance(tags.get("open_source"), bool):
        tags["open_source"] = False

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(tags, ensure_ascii=False, indent=2))
    return tags
