from pathlib import Path
from typing import Literal, Optional, Self

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from pymc_core.companion.constants import DEFAULT_MAX_CHANNELS, DEFAULT_MAX_CONTACTS

from mcbot.utils.board_configs import BOARD_LITERAL

import yaml
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

class Channel(BaseModel):
    name: str
    type: Literal["private", "hashtag"]
    secret: Optional[str] = None
    
class SQLite(BaseModel):
    path: str = "storage.db"
    
class Scoring(BaseModel):
    infrastructure_weight: float = 0.40
    hop_weight: float = 0.35
    path_bonus_weight: float = 0.15
    freshness_weight: float = 0.10
    base_delay_ms: int = 2000
    min_delay_ms: int = 100
    max_jitter_ms: int = 200
    degrade_after_seconds: int = 3600
    degrade_target: float = 0.5
    degrade_window_seconds: int = 86400
    fallback_min_delivery_score: float = 0.30
    min_signal_score: float = 0.30
    
class Coordinator(BaseModel):
    url: str = ""
    registration_key: str = ""
    bot_token: str = ""
    heartbeat_interval: int = 30
    coordination_timeout_ms: int = 500
    batch_interval_seconds: int = 5
    batch_max_size: int = 50
    mesh_region: str = ""
    scoring: Scoring = Scoring()
    
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
    
class Settings(BaseSettings, case_sensitive=False):
    name: str = "MCBot"
    prefix: str = "/"
    hardware: BOARD_LITERAL
    max_channels: int = DEFAULT_MAX_CHANNELS
    max_contacts: int = DEFAULT_MAX_CONTACTS
    radio: Radio
    logging: Logging = Logging()
    identity: Optional[str] = None
    channels: list[Channel] = Field(default_factory=list)
    letsmesh: Optional[LetsMesh] = None
    sqlite: Optional[SQLite] = None
    coordinator: Coordinator = Coordinator()
    
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