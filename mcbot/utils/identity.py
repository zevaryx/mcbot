import logging
import os
from pathlib import Path

from pymc_core import LocalIdentity

logger = logging.getLogger(__name__)

def create_or_load_identity(identity: str | None = None) -> LocalIdentity:
    saved_seed = Path.home() / ".config/mcbot/identity.key"
    if identity:
        logger.info("Using existing identity seed")
        seed = bytes.fromhex(identity)
        if len(seed) != 32:
            raise ValueError(f"Identity seed expected 32 bytes, got {len(seed)}")
        saved_seed.parent.mkdir(parents=True, exist_ok=True)
        saved_seed.write_bytes(seed)
        os.chmod(saved_seed, 0o600)
        return LocalIdentity(seed=seed)
    else:
        seed = os.urandom(32)
        saved_seed.parent.mkdir(parents=True, exist_ok=True)
        saved_seed.write_bytes(seed)
        os.chmod(saved_seed, 0o600)
        logger.info(f"Generated new identity and saved to { saved_seed}")
        return LocalIdentity(seed=seed)
        