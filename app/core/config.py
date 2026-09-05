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

    # --- LLM (8.15 D11) ---
    # One vendor, OpenAI, for all three call sites. Section 9 locks the
    # embedding model, which is OpenAI's, so the vendor question was only ever
    # about generation. base_url + model are plain config values - not a
    # provider registry (section 13).
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""

    generation_model: str = "gpt-5.6-luna"
    generation_effort: Literal["none", "low", "medium", "high", "max"] = "low"
    judge_model: str = "gpt-5.6-terra"          # section 7's judge
    embedding_model: str = "text-embedding-3-small"

    # D6's retrieval embed is the only network call inside compose, so it is
    # where 8.6's timeout and fallback to HierarchicalDecay live. Chosen, not
    # specified: 8.6 fixes the 1-2s whole-compose budget, not this slice of it.
    retrieval_timeout_seconds: float = 1.0



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



