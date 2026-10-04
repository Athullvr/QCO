from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://qco:qco@localhost:5432/qco"
    data_dir: Path = Path("./data")

    user_agent: str = "QCOWatch/0.1 (+contact: set USER_AGENT in .env)"
    min_request_interval_s: float = 2.0
    listing_ttl_hours: float = 12.0
    request_timeout_s: float = 45.0

    anakin_api_key: SecretStr = SecretStr("")
    anakin_max_credits: int = 0
    anakin_base_url: str = "https://api.anakin.io/v1"

    llm_provider: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_base_url: str = ""
    llm_json_mode: str = "json_schema"  # or json_object
    embed_provider: str = ""  # "" = local fastembed (no key) | openai
    embed_model: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""

    @property
    def raw_dir(self) -> Path: return self.data_dir / "raw"
    @property
    def text_dir(self) -> Path: return self.data_dir / "text"
    @property
    def drop_dir(self) -> Path: return self.data_dir / "drop"
    @property
    def gold_dir(self) -> Path: return self.data_dir / "gold"
    @property
    def report_dir(self) -> Path: return self.data_dir / "reports"
    @property
    def anakin_cache_dir(self) -> Path: return self.data_dir / "anakin_cache"
    @property
    def anakin_ledger(self) -> Path: return self.data_dir / "anakin_ledger.jsonl"


settings = Settings()
DISCLAIMER = "Informational only. Check the official notification."
