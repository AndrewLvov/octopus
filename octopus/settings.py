import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings



load_dotenv()

class Settings(BaseSettings):
    pguser: str
    pgpassword: str
    pghost: str
    pgport: str
    pgdatabase: str
    # Gmail API settings
    gmail_credentials_path: str | None = None  # Path to client_secret.json
    gmail_token_path: str | None = None  # Path to store/load token.json
    hacker_news_api_key: str | None = None
    slack_webhook: str | None = None
    # Telegram settings
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    telegram_channels: list[str] = []

    # Azure OpenAI settings
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_version: str = "2024-08-01-preview"
    azure_openai_deployment_name: str = "gpt-4o"

    # DiffBot API settings
    diffbot_api_key: str

    model_config = {
        "env_file": ".env",
        "extra": "allow"
    }

    @property
    def database_url(self) -> str:
        return f"postgresql+psycopg2://{self.pguser}:{self.pgpassword}@{self.pghost}:{self.pgport}/{self.pgdatabase}"

settings = Settings()

