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

    # Supabase / database
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/qbcals"

    # Celery / Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"


settings = Settings()
