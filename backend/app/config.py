from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    CACHE_DIR: str = "data/cache"
    MAX_VIDEO_MINUTES: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
