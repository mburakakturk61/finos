from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Uygulama ayarları. Ortam değişkenlerinden (ve varsa .env dosyasından)
    okunur. Buraya asla gerçek gizli bilgi (şifre, token) yazılmaz —
    beklenen değişken adları için .env.example dosyasına bakınız.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://finos:changeme@localhost:5432/finos"
    )

    trial_balance_max_upload_bytes: int = 10 * 1024 * 1024

    default_page_limit: int = 50
    max_page_limit: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
