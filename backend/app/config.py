from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql://realestate_user:realestate_pass@localhost:5433/realestate_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6380/0"

    # Qdrant (vector store)
    QDRANT_URL: str = "http://localhost:6333"

    # Ollama (local, free)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_CHAT_MODEL: str = "llama3.2"        # pull with: ollama pull llama3.2
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"  # pull with: ollama pull nomic-embed-text

    # External APIs
    GEOAPIFY_API_KEY: str = ""

    # Email — Gmail SMTP with App Password
    # Generate one at: myaccount.google.com/apppasswords (requires 2FA enabled)
    GMAIL_ADDRESS: str = ""       # your Gmail address, e.g. you@gmail.com
    GMAIL_APP_PASSWORD: str = ""  # 16-char App Password, NOT your regular password
    EMAIL_TO: str = ""            # recipient — can be the same as GMAIL_ADDRESS

    # Observability backend (the electronics project)
    LLM_OBSERVER_URL: str = "http://localhost:8000"
    LLM_OBSERVER_API_KEY: str = ""

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8001
    DEBUG: bool = True


settings = Settings()
