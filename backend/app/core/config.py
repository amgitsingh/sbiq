from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
