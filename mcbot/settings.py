from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from mcbot.utils.board_configs import BOARD_LITERAL

import yaml
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

_SETTINGS: Settings = None # type: ignore

class Channel(BaseModel):
    name: str
    type: Literal["private", "hashtag"]
    secret: Optional[str] = None
    
class Radio(BaseModel):
    frequency: float
    bandwidth: float
    spreading_factor: int
    coding_rate: int
    sync_word: int = 13380
    
class Logging(BaseModel):
    level: str = "INFO"
    format: str = "[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
    
class Settings(BaseSettings, case_sensitive=False):
    name: str = "MCBot"
    prefix: str = "/"
    hardware: BOARD_LITERAL
    radio: Radio
    logging: Logging = Logging()
    identity: Optional[str] = None
    channels: list[Channel] = Field(default_factory=list)
    
def load_settings(path: str | Path = Path("config.yaml")) -> Settings:
    """Load settings from a yaml config.
    
    Args:
        path: Path to the config file
        
    Return:
        Singleton instance of settings
    """
    path = Path(path)
    global _SETTINGS
    if not _SETTINGS:
        if not path.exists():
            raise ValueError(f"Config does not exist at {path}")
        
        with path.open() as f:
            data = yaml.load(f, Loader=Loader)
        
        _SETTINGS = Settings(**data)
    return _SETTINGS