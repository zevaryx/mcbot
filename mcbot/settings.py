from pathlib import Path
from typing import Literal, Optional, ClassVar, Any, Self

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from mcbot.utils.board_configs import BOARD_LITERAL

import yaml
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader
    
class SingletonSettings(BaseSettings):
    """A Singleton settings instance class."""
    
    _instance: ClassVar[Any | None] = None
    
    def __new__(cls: type[Self], *args, **kwargs) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance
    
    @classmethod
    def load_settings(cls: type[Self], path: str | Path = Path("config.yaml")) -> Self:
        """Load settings from a yaml config.
    
        Args:
            path: Path to the config file
            
        Return:
            Singleton instance of settings
        """
        path = Path(path)
        if not path.exists():
            raise ValueError(f"Config file not found: {path}")
        with path.open() as f:
            data = yaml.load(f, Loader=Loader)
        return cls(**data)

_SETTINGS: Settings = None # type: ignore

class Channel(BaseModel):
    name: str
    type: Literal["private", "hashtag"]
    secret: Optional[str] = None
    
class SQLite(BaseModel):
    path: str = "storage.db"
    
class Broker(BaseModel):
    name: str
    host: str
    port: int
    audience: str
    jwt_expiry_minutes: int = 10
    use_tls: bool = True
    owner: Optional[str] = None
    email: Optional[str] = None
    
class LetsMesh(BaseModel):
    enabled: bool = False
    iata: Optional[str] = None
    status_interval: int = 300
    disallowed_packet_types: list[str] = Field(default_factory=list)
    brokers: list[Broker] = Field(default_factory=list)   
    
class Radio(BaseModel):
    frequency: float
    bandwidth: float
    spreading_factor: int
    coding_rate: int
    sync_word: int = 13380
    
class Logging(BaseModel):
    level: str = "INFO"
    format: str = "[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
    
class Settings(SingletonSettings, case_sensitive=False):
    name: str = "MCBot"
    prefix: str = "/"
    hardware: BOARD_LITERAL
    radio: Radio
    logging: Logging = Logging()
    identity: Optional[str] = None
    channels: list[Channel] = Field(default_factory=list)
    letsmesh: Optional[LetsMesh] = None
    sqlite: Optional[SQLite] = None
    
def load_settings(path: str | Path = Path("config.yaml")) -> Settings:
    
    path = Path(path)
    global _SETTINGS
    if not _SETTINGS:
        if not path.exists():
            raise ValueError(f"Config does not exist at {path}")
        
        with path.open() as f:
            data = yaml.load(f, Loader=Loader)
        
        _SETTINGS = Settings(**data)
    return _SETTINGS