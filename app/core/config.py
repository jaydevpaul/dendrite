from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://dendrite:dendrite@localhost:5432/dendrite"
    db_echo: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DENDRITE_")


settings = Settings()
