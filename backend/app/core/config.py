from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    """Comma-separated .env value -> list, e.g. "a, b,c" -> ["a", "b", "c"].
    A bare "*" stays a single-item ["*"] list (the CORSMiddleware wildcard),
    not split on nothing."""
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AI / LLM
    AI_API_KEY: str = ""
    AI_BASE_URL: str = "https://api.openai.com/v1"
    AI_MODEL: str = "gpt-4o"
    AI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    AI_MAX_TOKENS_PER_RUN: int = 100_000

    # External APIs
    TAVILY_API_KEY: str = ""
    CRUNCHBASE_API_KEY: str = ""

    # Enrichment source toggles — plug individual sources in/out without code
    # changes (e.g. Crunchbase off until a paid API key is purchased).
    ENABLE_WEBSITE_SCRAPER: bool = True
    ENABLE_TAVILY_WEB_SEARCH: bool = True
    ENABLE_TAVILY_PERSON_SEARCH: bool = True
    ENABLE_TAVILY_NEWS_SEARCH: bool = True
    ENABLE_CRUNCHBASE: bool = False
    ENABLE_LINKEDIN_SCRAPER: bool = True

    # LLM normalization can search the web itself (OpenAI Responses API hosted
    # tool) to fill gaps the 5 sources above missed. OpenAI-specific - not a
    # generic "OpenAI-compatible" capability, so turn this off if AI_BASE_URL
    # ever points at a different provider.
    ENABLE_LLM_WEB_SEARCH: bool = True

    # Cross-event enrichment reuse - if the same email was already enriched
    # recently (any event), reuse that structured profile instead of
    # re-running the 5 sources + LLM normalization from scratch.
    ENABLE_ENRICHMENT_REUSE: bool = True
    ENRICHMENT_REUSE_MAX_AGE_DAYS: int = 30

    # Supabase / database
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/qbcals"

    # Celery / Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Email (SMTP) — used to deliver a match's email_draft "on behalf of" the
    # participant who selected the match. Generic SMTP, not SendGrid/Resend
    # (CLAUDE.md names both as the eventual Phase 2 options; this is a
    # lighter-weight interim path — swap providers later without touching
    # callers, since app.services.email_sender is the only place that reads
    # these).
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    # The actual `From` address — always this, never a participant's own
    # address. See email_sender.send_email's docstring for why.
    SMTP_FROM_EMAIL: str = ""

    # Auth (docs/PLAN.md Phase 8 — merge with IndMatchmaking). Ported
    # verbatim from IndMatchmaking's Settings — same field names/defaults,
    # so its ported auth code (app/services/auth/) needs no changes here.
    # JWT_SECRET_KEY's default is a placeholder, not a real secret — must be
    # overridden via .env in any real deployment.
    JWT_SECRET_KEY: str = "change-this-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 720

    # Fernet key encrypting SmtpMaster.password_encrypted (per-user SMTP
    # credentials, Task 60). Falls back to deriving a key from JWT_SECRET_KEY
    # if unset (see app/services/auth/security.py._credential_cipher) - set a
    # real one via .env for anything beyond local dev.
    SMTP_ENCRYPTION_KEY: str | None = None

    # Alternate email-delivery path for admin/registration emails
    # (app/services/microsoft_graph_mail.py) - app-only Graph API send,
    # tried before falling back to a UserMaster's own SmtpMaster row. Unset
    # by default (is_microsoft_graph_mail_configured() gates on all three
    # being present), same degrade-gracefully convention as
    # ENABLE_CRUNCHBASE/etc.
    MICROSOFT_GRAPH_TENANT_ID: str | None = None
    MICROSOFT_GRAPH_CLIENT_ID: str | None = None
    MICROSOFT_GRAPH_CLIENT_SECRET: SecretStr | None = None
    MICROSOFT_GRAPH_TIMEOUT_SECONDS: float = 20.0

    # Link included in activation emails - the frontend's login page.
    MATCHMAKING_APPLICATION_URL: str = "http://localhost:8024/login"

    # Gates X-API-Key enforcement on /external/* (Task 61) - those routes
    # stay open (no check) if unset, same "off means skip the check, not
    # error" convention as every other optional toggle in this file. Set a
    # real key via .env before exposing this beyond local dev - the payloads
    # carry participant contact details.
    EXTERNAL_API_KEY: SecretStr | None = None

    # CORS (Task 69 - IndMatchmaking's create_app() made these configurable
    # via settings rather than hardcoded; adopted here for the same reason,
    # not because two apps are being merged - main.py is and stays the sole
    # app factory). Kept as plain comma-separated strings, not list[str] -
    # pydantic-settings tries to JSON-decode any "complex" (list) field's
    # raw env value *before* any field_validator runs, so a plain CSV value
    # like "https://a.com,https://b.com" crashes outright at Settings()
    # construction (`json.decoder.JSONDecodeError`), not just at validation
    # time. main.py splits these via _split_csv() at the point of use, which
    # sidesteps that entirely. Defaults preserve this app's pre-existing
    # wide-open local-dev behavior (main.py previously hardcoded "*" for all
    # three) - override via .env for any real deployment, e.g.
    # ALLOWED_CORS_ORIGINS=https://admin.example.com,https://app.example.com
    ALLOWED_CORS_ORIGINS: str = "*"
    CORS_ALLOW_METHODS: str = "*"
    CORS_ALLOW_HEADERS: str = "*"


settings = Settings()
