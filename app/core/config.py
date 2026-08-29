import secrets
import warnings
from datetime import timedelta
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://dendrite:dendrite@localhost:5433/dendrite"
    db_echo: bool = False

    #---auth----
    secret_key : str =""
    access_token_ttl: timedelta = timedelta(days=7)
    cookie_name: str = "session"

    cookie_secure:bool=False
    cookie_samesite: Literal["lax","strict","none"]="lax"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DENDRITE_")


    @model_validator(mode="after")
    def _ensure_secret_key(self)->"Settings":

        if not self.secret_key:
            self.secret_key=secrets.token_urlsafe(32)
            warnings.warn(
                "DENDRITE_SECRET_KEY is not set - generated an ephemeral key. "
                "Every session will be invalidated on restart. "
                "Set it in .env before doing anything real.",
                stacklevel=2,
            )

        return self


settings = Settings()
