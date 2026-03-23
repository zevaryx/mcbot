import logging
from typing import TYPE_CHECKING, Any
from pymc_core import LocalIdentity, MeshNode
from pymc_core.hardware.base import LoRaRadio

from mcbot.utils.board_configs import HARDWARE_CONFIGS
from mcbot.utils.identity import create_or_load_identity

if TYPE_CHECKING:
    from mcbot.settings import Settings

logger = logging.getLogger(__name__)

def get_radio_str(settings: Settings) -> str:
    radio_freq = settings.radio.frequency
    radio_bw = settings.radio.bandwidth
    radio_sf = settings.radio.spreading_factor
    radio_cr = settings.radio.coding_rate
    
    return f"{radio_freq},{radio_bw},{radio_sf},{radio_cr}"

def create_radio(settings: Settings) -> tuple[LoRaRadio, dict[str, Any]]:
    """Create a radio instance with the specified hardware configuration.
    
    Args:
        radio_type: Bot settings
    Returns:
        Radio instance
    """
    logger.info(f"Creatintg radio for {settings.hardware}")
    try:
        from pymc_core.hardware.sx1262_wrapper import create_sx1262_radio
        logger.debug("Imported SX1262Radio")
        
        spi_config = HARDWARE_CONFIGS.get(settings.hardware)
        if not spi_config:
            raise ValueError(f"Unknown hardware type {settings.hardware}")
        radio_config = settings.radio.model_dump()
        
        combined_config = {
            "bus_id": spi_config["bus_id"],
            "cs_id": spi_config["cs_id"],
            "cs_pin": spi_config["cs_pin"],
            "reset_pin": spi_config["reset_pin"],
            "busy_pin": spi_config["busy_pin"],
            "irq_pin": spi_config["irq_pin"],
            "txen_pin": spi_config["txen_pin"],
            "rxen_pin": spi_config["rxen_pin"],
            "txled_pin": spi_config.get("txled_pin", -1),
            "rxled_pin": spi_config.get("rxled_pin", -1),
            "en_pin": spi_config.get("en_pin", -1),
            "use_dio3_tcxo": spi_config.get("use_dio3_tcxo", False),
            "dio3_tcxo_voltage": float(spi_config.get("dio3_tcxo_voltage", 1.8)),
            "use_dio2_rf": spi_config.get("use_dio2_rf", False),
            "is_waveshare": spi_config.get("is_waveshare", False),
            "frequency": int(radio_config["frequency"] * 1000000),
            "tx_power": spi_config["tx_power"],
            "spreading_factor": radio_config["spreading_factor"],
            "bandwidth": int(radio_config["bandwidth"] * 1000),
            "coding_rate": radio_config["coding_rate"],
            "preamble_length": spi_config["preamble_length"],
            "sync_word": ["sync_word"],
        }
        
        if "gpio_chip" in spi_config:
            combined_config["gpio_chip"] = spi_config["gpio_chip"]
        if "use_gpiod_backend" in spi_config:
            combined_config["use_gpiod_backend"] = spi_config["use_gpiod_backend"]
        
        logger.debug(f"Radio config for {settings.hardware}: {combined_config}")
        radio = create_sx1262_radio(**combined_config)
        logger.info(f"SX1262 radio created for {settings.hardware}")
        logger.info(
            f"Frequency: {combined_config['frequency']/1000000:.1f}MHz, TX Power: {combined_config['tx_power']}dBm"
        )
        return radio, combined_config
        
    except Exception as e:
        logger.error(f"Failed to create SX1262 radio: {e}")
        logger.error(f"Error type: {type(e)}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        raise