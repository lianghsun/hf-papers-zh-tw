# HF Daily Paper 繁體中文翻譯系統

## 專案目標

每日自動抓取 HuggingFace Daily Papers，生成繁體中文翻譯靜態網站，並發送 email 摘要通知。

來源網址：`https://huggingface.co/papers/date/{YYYY-MM-DD}`

---

## 功能規格

### 每日自動化流程（UTC+8 早上 8:00 觸發）

1. **抓取今日論文清單**：從 HF daily papers 頁面取得所有論文 metadata
2. **翻譯 Abstract**：每篇 abstract 翻成繁體中文
3. **下載 PDF**：從 arxiv 下載完整 PDF
4. **解析 PDF**：用 PyMuPDF 解析段落文字 + 擷取所有圖表（PNG）
5. **全文翻譯**：整篇 paper 完整翻譯為繁體中文，圖表位置保留
6. **生成 Metadata Tags**：用 Claude 生成分類標籤（研究領域、方法、應用、資料集等）
7. **生成靜態網站**：每篇 paper 獨立 HTML 頁面 + 每日 index 頁 + 全站搜尋
8. **部署到 GitHub Pages**：自動 push 更新
9. **發送 Email 通知**：每日一封，含今日所有論文的繁中 abstract 清單 + 網站連結

---

## 技術架構

### 技術選型

| 元件 | 工具 | 備註 |
|------|------|------|
| 語言 | Python 3.11+ | |
| 套件管理 | `uv` | 速度快，現代工具 |
| 爬蟲 | `httpx` + `beautifulsoup4` | HF 頁面 + arxiv PDF |
| PDF 解析 | `pymupdf` (fitz) + **DotsOCR** | PyMuPDF 轉頁面圖片 + DotsOCR 解析結構 |
| 翻譯/AI | Claude API (`claude-haiku-4-5-20251001`) | 繁中品質佳，成本低 |
| 靜態網站 | 自訂 HTML 生成（Jinja2 模板） | 輕量，完全掌控樣式 |
| 搜尋 | `pagefind`（靜態搜尋） | 純靜態，無需後端 |
| 定時排程 | GitHub Actions cron | 免費，版本控管 |
| 部署 | GitHub Pages | 免費靜態托管 |
| Email | SendGrid / Gmail SMTP | 每日摘要通知 |

### 目錄結構

```
hf-daliy-paper/
├── CLAUDE.md
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── daily.yml          # GitHub Actions cron job
├── src/
│   ├── fetch_papers.py        # 抓取 HF daily papers 清單
│   ├── download_pdf.py        # 下載 arxiv PDF
│   ├── parse_pdf.py           # PyMuPDF 解析段落 + 圖表
│   ├── translate.py           # Claude API 翻譯（abstract + 全文）
│   ├── generate_tags.py       # Claude API 生成 metadata tags
│   ├── build_site.py          # 生成靜態 HTML
│   ├── send_email.py          # 發送每日 email 摘要
│   └── main.py                # 主流程入口
├── templates/
│   ├── paper.html             # 單篇論文頁面模板
│   ├── daily_index.html       # 每日清單頁面模板
│   └── base.html              # 共用 layout
├── docs/                      # GitHub Pages 輸出目錄
│   └── (generated)
└── data/
    └── (每日 JSON cache，避免重複翻譯)
```

---

## 資料流細節

### HF Papers API

```
GET https://huggingface.co/api/daily_papers?date={YYYY-MM-DD}
```
回傳每篇論文的 title、abstract、arxiv id、upvotes 等。

### PDF 來源

```
https://arxiv.org/pdf/{arxiv_id}
```

### PDF 解析策略（PyMuPDF + DotsOCR 混合）

**兩階段解析：**

1. **PyMuPDF**：將 PDF 每頁轉為高解析度 PNG 圖片
2. **DotsOCR API**（自架端點）：送入頁面圖片，取得結構化 layout JSON

**DotsOCR 輸出 JSON 結構：**
```json
[
  {"category": "Title",   "bbox": [x1,y1,x2,y2], "text": "..."},
  {"category": "Text",    "bbox": [x1,y1,x2,y2], "text": "Markdown 格式段落"},
  {"category": "Table",   "bbox": [x1,y1,x2,y2], "text": "<table>HTML</table>"},
  {"category": "Formula", "bbox": [x1,y1,x2,y2], "text": "LaTeX 公式"},
  {"category": "Picture", "bbox": [x1,y1,x2,y2]}   // 無 text，只有位置
]
```

**圖表擷取**（DotsOCR 只給 bbox，實際圖片靠 PyMuPDF 裁切）：
```python
# DotsOCR 偵測到 Picture 的 bbox → PyMuPDF 按座標裁切原 PDF 頁面 → 存 PNG
```

**DotsOCR API 呼叫方式：**
```python
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["DOTSOCR_ENDPOINT"],  # 存 GitHub Secret，不寫死
    api_key=os.environ["DOTSOCR_API_KEY"]     # 存 GitHub Secret，不寫死
)
response = client.chat.completions.create(
    model="dotsocr-model",
    messages=[{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page_b64}"}},
            {"type": "text", "text": "prompt_layout_all_en"}
        ]
    }],
    max_tokens=24000
)
```

**輸出結構化 JSON**：`[{type: "text"|"table"|"formula"|"image"|"title", content: ..., page: N, bbox: [...]}]`

### 翻譯策略（Claude API）

- 文字區塊以 2000 tokens 為單位分批送翻
- System prompt 強調：學術繁體中文、保留專有名詞英文、不省略內容
- 圖表 caption 單獨翻譯
- 每篇論文翻譯結果 cache 到 `data/{date}/{arxiv_id}.json`，避免重複付費

### Metadata Tags 分類

Claude 針對每篇 paper 生成以下維度的 tags：
- **領域**：NLP / CV / RL / Multimodal / Audio / ...
- **方法**：Transformer / Diffusion / RLHF / RAG / LoRA / ...
- **任務**：Text Generation / Image Classification / Code / ...
- **資料集**：如有提到
- **開源**：是否有公開 code/model

---

## 網站設計

- 每日 index 頁：`/YYYY-MM-DD/`，列出當日所有論文卡片（繁中標題 + abstract 摘要 + tags）
- 單篇論文頁：`/paper/{arxiv_id}/`，完整繁中全文翻譯 + 圖表
- 首頁：最近 30 天的 daily index 列表
- 全文搜尋：由 `pagefind` 在 build 時生成索引
- 按 tag 篩選功能

---

## Email 格式

每日一封，主旨：`[HF Papers] {YYYY-MM-DD} 今日 N 篇論文`

內容：
- 每篇論文：繁中標題 + 繁中 abstract（前 3 句）+ tags + 網站連結
- 底部：完整網站連結

---

## 環境變數（GitHub Actions Secrets）

```
ANTHROPIC_API_KEY    # Claude API（翻譯 + metadata tags）
DOTSOCR_ENDPOINT     # DotsOCR 自架端點 URL
DOTSOCR_API_KEY      # DotsOCR 自架端點 API Key
SENDGRID_API_KEY     # 或 GMAIL_APP_PASSWORD
EMAIL_TO             # 收件信箱
GITHUB_TOKEN         # 自動提供，用於 push to Pages
```

> **安全說明**：所有 API key 儲存於 GitHub Actions Secrets（加密），僅在 CI 執行期間注入為環境變數。
> GitHub Pages 只托管生成的靜態 HTML，其中完全不含任何 key，**不存在洩漏風險**。

---

## 成本估算

- Claude API（Haiku）：每篇 paper ~10K tokens × 20 篇/天 = 200K tokens/天
  - Input: $0.08/1M tokens → ~$0.016/天
  - Output: $0.40/1M tokens → ~$0.08/天（翻譯輸出量大）
  - 月估算：~$3–5 USD/月
- GitHub Actions：免費方案 2000 min/月，每日 job 約 10–15 min，綽綽有餘
- GitHub Pages：免費

---

## 開發順序

1. `src/fetch_papers.py` — 先驗證 HF API 可用性
2. `src/download_pdf.py` — arxiv PDF 下載
3. `src/parse_pdf.py` — PDF 解析測試
4. `src/translate.py` — Claude API 翻譯 abstract 測試
5. `src/generate_tags.py` — metadata tags 生成
6. `src/translate.py` — 全文翻譯（分段處理）
7. `templates/` + `src/build_site.py` — 靜態網站生成
8. `src/send_email.py` — email 通知
9. `src/main.py` — 串接完整流程
10. `.github/workflows/daily.yml` — GitHub Actions 排程
