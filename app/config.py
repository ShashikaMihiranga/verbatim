from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "production"  # set ENV=dev locally; anything else hides API docs
    database_url: str = "sqlite:///./dev.db"
    clerk_jwks_url: str | None = None
    clerk_issuer: str | None = None

    @property
    def sqlalchemy_url(self) -> str:
        """Railway gives postgres:// or postgresql://; use the psycopg 3 driver."""
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
