import os
from pathlib import Path
from dataclasses import dataclass, field


def _load_env_file(env_path: Path):
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                if key not in os.environ:
                    os.environ[key] = value


def _env_list(list_name: str, fallback_name: str = "") -> list[str]:
    raw = os.environ.get(list_name, "")
    if not raw and fallback_name:
        raw = os.environ.get(fallback_name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


# 优先级：系统环境变量 > 项目根目录 .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_load_env_file(PROJECT_ROOT / ".env")


@dataclass
class Config:
    DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
    TAVILY_API_KEY: str = os.environ.get("TAVILY_API_KEY", "")
    TAVILY_API_KEYS: list[str] = field(
        default_factory=lambda: _env_list("TAVILY_API_KEYS", "TAVILY_API_KEY")
    )
    YOUTUBE_API_KEY: str = os.environ.get("YOUTUBE_API_KEY", "")
    GOOGLE_MAPS_API_KEY: str = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    PEXELS_API_KEY: str = os.environ.get("PEXELS_API_KEY", "")
    UNSPLASH_ACCESS_KEY: str = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    SCREENSHOT_PROVIDER: str = os.environ.get("SCREENSHOT_PROVIDER", "local")
    SCREENSHOT_API_URL: str = os.environ.get("SCREENSHOT_API_URL", "")
    SCREENSHOT_API_KEY: str = os.environ.get("SCREENSHOT_API_KEY", "")
    IMAGE_API_KEY: str = os.environ.get("IMAGE_API_KEY", "")
    IMAGE_API_URL: str = os.environ.get(
        "IMAGE_API_URL", "https://api.openai.com/v1/images/generations"
    )
    FLASK_PORT: int = int(os.environ.get("FLASK_PORT", "5050"))

    # 数据库路径，开发环境默认在当前项目 db/ 下
    DB_PATH_RESEARCH: str = os.environ.get(
        "DB_PATH_RESEARCH",
        str(PROJECT_ROOT / "db" / "research_db.sqlite"),
    )
    DB_PATH_FINAL: str = os.environ.get(
        "DB_PATH_FINAL",
        str(PROJECT_ROOT / "db" / "final_db.sqlite"),
    )
    DB_PATH_ASSETS: str = os.environ.get(
        "DB_PATH_ASSETS",
        str(PROJECT_ROOT / "db" / "assets_db.sqlite"),
    )
    DB_PATH_COMPOSITION: str = os.environ.get(
        "DB_PATH_COMPOSITION",
        str(PROJECT_ROOT / "db" / "composition_db.sqlite"),
    )
    DB_PATH_TEMPLATE: str = os.environ.get(
        "DB_PATH_TEMPLATE",
        str(PROJECT_ROOT / "db" / "template_db.sqlite"),
    )
    IMAGES_DIR: str = os.environ.get(
        "IMAGES_DIR",
        str(PROJECT_ROOT / "images"),
    )

    # Playwright
    PLAYWRIGHT_CHROMIUM_PATH: str = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH", "")

    # DeepSeek API
    DEEPSEEK_API_URL: str = os.environ.get(
        "DEEPSEEK_API_URL",
        "https://api.deepseek.com/chat/completions",
    )
    DEEPSEEK_MODEL: str = "deepseek-v4-pro"
    DEEPSEEK_FLASH_MODEL: str = "deepseek-v4-flash"

    # 研究深度与预算
    RESEARCH_DEPTH: str = os.environ.get("RESEARCH_DEPTH", "standard")
    TAVILY_QUERY_BUDGET_STANDARD: int = int(os.environ.get("TAVILY_QUERY_BUDGET_STANDARD", "14"))
    TAVILY_QUERY_BUDGET_DEEP: int = int(os.environ.get("TAVILY_QUERY_BUDGET_DEEP", "18"))
    TAVILY_RESULTS_PER_QUERY: int = int(os.environ.get("TAVILY_RESULTS_PER_QUERY", "5"))
    TAVILY_ADAPTIVE_MODE: bool = os.environ.get("TAVILY_ADAPTIVE_MODE", "1") == "1"
    TAVILY_INITIAL_QUERY_LIMIT: int = int(os.environ.get("TAVILY_INITIAL_QUERY_LIMIT", "8"))
    TAVILY_INITIAL_SEARCH_DEPTH: str = os.environ.get("TAVILY_INITIAL_SEARCH_DEPTH", "basic")
    TAVILY_INITIAL_INCLUDE_RAW_CONTENT: bool = os.environ.get("TAVILY_INITIAL_INCLUDE_RAW_CONTENT", "0") == "1"
    TAVILY_ESCALATE_SEARCH_DEPTH: str = os.environ.get("TAVILY_ESCALATE_SEARCH_DEPTH", "advanced")
    TAVILY_ESCALATE_INCLUDE_RAW_CONTENT: bool = os.environ.get("TAVILY_ESCALATE_INCLUDE_RAW_CONTENT", "0") == "1"
    TAVILY_ESCALATE_RAW_CONTENT_INTENTS: list[str] = field(
        default_factory=lambda: _env_list(
            "TAVILY_ESCALATE_RAW_CONTENT_INTENTS"
        ) or ["market_size", "pricing_details", "customers", "unit_economics"]
    )
    TAVILY_SEARCH_DEPTH: str = os.environ.get("TAVILY_SEARCH_DEPTH", "advanced")
    TAVILY_INCLUDE_RAW_CONTENT: bool = os.environ.get("TAVILY_INCLUDE_RAW_CONTENT", "1") == "1"
    TAVILY_CACHE_TTL_SECONDS: int = int(os.environ.get("TAVILY_CACHE_TTL_SECONDS", "86400"))
    COLLECTION_MIN_UNIQUE_URLS: int = int(os.environ.get("COLLECTION_MIN_UNIQUE_URLS", "18"))
    COLLECTION_ENABLE_GAP_REFETCH: bool = os.environ.get("COLLECTION_ENABLE_GAP_REFETCH", "1") == "1"
    EVIDENCE_SPAN_BINDING_ENABLED: bool = os.environ.get("EVIDENCE_SPAN_BINDING_ENABLED", "1") == "1"
    COLLECTION_WEBSITE_SUFFICIENT_CHARS: int = int(os.environ.get("COLLECTION_WEBSITE_SUFFICIENT_CHARS", "1500"))
    COLLECTION_GAP_QUERY_LIMIT: int = int(os.environ.get("COLLECTION_GAP_QUERY_LIMIT", "4"))

    # ── 噪音与上下文治理 ──
    L0_CONTEXT_BUDGET_TOKENS: int = int(os.environ.get("L0_CONTEXT_BUDGET_TOKENS", "18000"))
    DOCUMENT_CHUNKING_ENABLED: bool = os.environ.get("DOCUMENT_CHUNKING_ENABLED", "1") == "1"
    CONTEXT_PACKER_ENABLED: bool = os.environ.get("CONTEXT_PACKER_ENABLED", "1") == "1"
    RAW_TEXT_IN_LLM_ENABLED: bool = os.environ.get("RAW_TEXT_IN_LLM_ENABLED", "0") == "1"
    POSTHOC_EVIDENCE_WEAK_ONLY: bool = os.environ.get("POSTHOC_EVIDENCE_WEAK_ONLY", "1") == "1"

    # ── SPEC v3 新增：字段契约与质量闸门 ──
    FORUM_MODERATOR_ENABLED: bool = os.environ.get("FORUM_MODERATOR_ENABLED", "1") == "1"
    AGENT_DEBATE_ENABLED: bool = os.environ.get("AGENT_DEBATE_ENABLED", "0") == "1"
    MAX_CHUNKS_PER_URL: int = int(os.environ.get("MAX_CHUNKS_PER_URL", "3"))
    MAX_CHUNKS_PER_SOURCE_FAMILY: int = int(os.environ.get("MAX_CHUNKS_PER_SOURCE_FAMILY", "12"))
    MAX_EVIDENCE_SPANS_PER_FIELD: int = int(os.environ.get("MAX_EVIDENCE_SPANS_PER_FIELD", "3"))
    CARD_SCHEMA_VERSION: str = os.environ.get("CARD_SCHEMA_VERSION", "v3")
    FIELD_MANIFEST_REQUIRED: bool = os.environ.get("FIELD_MANIFEST_REQUIRED", "1") == "1"
    ENTITY_TABLES_PRIMARY: bool = os.environ.get("ENTITY_TABLES_PRIMARY", "1") == "1"
    USE_FIELD_DRIVEN_COLLECTION: bool = os.environ.get("USE_FIELD_DRIVEN_COLLECTION", "1") == "1"

    # ── SourceAdapter 预算 ──
    COLLECTION_BUDGET_OFFICIAL_SITE: int = int(os.environ.get("COLLECTION_BUDGET_OFFICIAL_SITE", "5"))
    COLLECTION_BUDGET_TAVILY_SEARCH: int = int(os.environ.get("COLLECTION_BUDGET_TAVILY_SEARCH", "14"))
    COLLECTION_BUDGET_TAVILY_EXTRACT: int = int(os.environ.get("COLLECTION_BUDGET_TAVILY_EXTRACT", "20"))
    COLLECTION_BUDGET_GITHUB: int = int(os.environ.get("COLLECTION_BUDGET_GITHUB", "3"))
    COLLECTION_BUDGET_PRODUCTHUNT: int = int(os.environ.get("COLLECTION_BUDGET_PRODUCTHUNT", "3"))
    COLLECTION_BUDGET_YOUTUBE: int = int(os.environ.get("COLLECTION_BUDGET_YOUTUBE", "3"))
    COLLECTION_BUDGET_SEC: int = int(os.environ.get("COLLECTION_BUDGET_SEC", "5"))
    COLLECTION_BUDGET_BENCHMARK: int = int(os.environ.get("COLLECTION_BUDGET_BENCHMARK", "5"))

config = Config()
