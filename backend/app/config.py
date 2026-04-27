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
    QDRANT_API_KEY: str = ""

    # Embeddings — using Hugging Face (nomic-embed-text via sentence-transformers)
    EMBEDDING_MODEL: str = "nomic-ai/nomic-embed-text-v1.5"

    # External APIs
    GEOAPIFY_API_KEY: str = ""
    RAPIDAPI_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    HF_API_TOKEN: str = ""
    GOOGLE_MAPS_API_KEY: str = ""
    NOMIC_API_KEY: str = ""

    # Email — Gmail SMTP with App Password
    # Generate one at: myaccount.google.com/apppasswords (requires 2FA enabled)
    GMAIL_ADDRESS: str = ""       # your Gmail address, e.g. you@gmail.com
    GMAIL_APP_PASSWORD: str = ""  # 16-char App Password, NOT your regular password
    EMAIL_TO: str = ""            # recipient — can be the same as GMAIL_ADDRESS

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8001
    DEBUG: bool = True


settings = Settings()
