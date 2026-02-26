import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = BASE_DIR / "docs"
TEMPLATES_DIR = BASE_DIR / "templates"

# APIs
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DOTSOCR_ENDPOINT = os.environ["DOTSOCR_ENDPOINT"]
DOTSOCR_API_KEY = os.environ["DOTSOCR_API_KEY"]

# Email
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]

# Models
TRANSLATE_MODEL = "claude-haiku-4-5-20251001"
DOTSOCR_MODEL = "dotsocr-model"

# Site
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://lianghsun.github.io/hf-papers-zh-tw")
SITE_TITLE = "HF Papers 繁中"
