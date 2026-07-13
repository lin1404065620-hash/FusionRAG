from dataclasses import dataclass
import os


@dataclass
class MineruConfig:
    base_url: str
    api_key : str

mineru_config = MineruConfig(
    base_url=os.getenv("MINERU_BASE_URL", "https://mineru.net/api/v4"),
    api_key=os.getenv("MINERU_API_TOKEN", "")
)
