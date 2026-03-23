import asyncio
import logging
from hashlib import sha256
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from pymc_core import LocalIdentity
from pymc_core.companion.companion_base import CompanionBase
from pymc_core.companion.constants import (
    ADV_TYPE_CHAT,
    DEFAULT_MAX_CHANNELS,
    DEFAULT_MAX_CONTACTS,
    DEFAULT_OFFLINE_QUEUE_SIZE,
)
from pymc_core.node.node import MeshNode
from pymc_core.protocol.constants import (
    PAYLOAD_TYPE_GRP_TXT,
    PAYLOAD_TYPE_TXT_MSG,
)
from pymc_core.protocol.packet import Packet

from mcbot.helpers.letsmesh import LetsMeshHelper
from mcbot.models.internal.command import Command, CallbackType
from mcbot.models.internal.context import Context
from mcbot.models.internal.task import Task
from mcbot.models.internal.triggers import IntervalTrigger, TimeTrigger
from mcbot.utils.board_configs import HARDWARE_CONFIGS
from mcbot.utils.identity import create_or_load_identity
from mcbot.utils.radio import create_radio

if TYPE_CHECKING:
    from mcbot.settings import Settings

class Bot(CompanionBase):
    node: MeshNode
    logger: logging.Logger
    
    _settings: Settings
    _identity: LocalIdentity
    _packet_cache: dict[str, float]
    _start_time: datetime
    _dispatcher_task: Optional[asyncio.Task]
    _packets_sent: int
    _packets_received: int
    _letsmesh: LetsMeshHelper
    
    __commands: list[Command]
    __tasks: list[Task]
    
    def __init__(self, settings: Settings):
        logging.basicConfig(level=settings.logging.level, format=settings.logging.format)
        self.logger = logging.getLogger(__name__)
        logging.debug(f"Creating bot with name {settings.name}")
        self._settings = settings
        self._identity = create_or_load_identity(self._settings.identity)
        self._radio, self._radio_config = create_radio(self._settings)
        self.logger.info(f"Radio in use: {HARDWARE_CONFIGS[self._settings.hardware]['name']}")
        self.logger.info(f"Frequency info: freq={self._radio_config['frequency']}")
        self.__commands: list[Command] = []
        self.__tasks: list[Task] = []
        self._packet_cache: dict[str, float] = {}
        
        self._packets_sent = 0
        self._packets_received = 0
        
        # TODO:
        # - Add max_contacts, max_channels, and offline_queue_size to config
        # - Add a way to load contacts before initialization
        self._init_companion_stores(
            identity=self._identity,
            node_name=self._settings.name,
            adv_type=ADV_TYPE_CHAT,
            max_contacts=DEFAULT_MAX_CONTACTS,
            max_channels=DEFAULT_MAX_CHANNELS,
            offline_queue_size=DEFAULT_OFFLINE_QUEUE_SIZE,
            radio_config=self._radio_config,
            initial_contacts=None,
        )
        self._dispatcher_task: Optional[asyncio.Task] = None
        self._letsmesh = LetsMeshHelper(self._settings, self._identity, self._live_stats)
        
        self.task(Task(self._cleanup_cache, IntervalTrigger(minutes=5)))
        self.task(Task(self._advert, TimeTrigger(hour=12)))
        self.task(Task(self._advert, TimeTrigger(hour=0)))
        
    @property
    def is_running(self) -> bool:
        return self._running
    
    ############
    # Lifespan #
    ############
    
    async def start(self):
        """Start the bot."""
        if self.is_running:
            self.logger.warning("Bot is already running!")
            return
        
        self.logger.info("Starting bot!")
        self.node = MeshNode(
            radio=self._radio,
            local_identity=self._identity,
            config={
                "node": {"name": self._settings.name},
                "radio": self._radio_config,
            },
            contacts=self.contacts,
            channel_db=self.channels,
            event_service=self._event_service,
        )
        self._setup_packet_callbacks()
        
        for idx, channel in enumerate(self._settings.channels):
            secret = channel.secret
            if not secret:
                if channel.type == "hashtag":
                    secret = sha256(channel.name.encode("UTF-8")).hexdigest()[:32]
                elif channel.type == "private":
                    self.logger.error(f"No secret provided for channel: {channel.name}")
                    continue
                else:
                    self.logger.error(f"Unknown channel type: {channel.type}")
                    continue
            secret = bytes.fromhex(secret)
            self.logger.debug(f"Adding channel {channel.name}...")
            if not self.set_channel(idx=idx+1, name=channel.name, secret=secret):
                self.logger.error(f"Failed to create channel: {channel.name}")
        
        self._running = True
        self._start_time = datetime.now()
        self._letsmesh.connect()
        
        self.node.dispatcher.set_default_path_hash_mode(self.prefs.path_hash_mode)
        self._dispatcher_task = asyncio.create_task(self.node.start())
        self.logger.info(
            f"Bot started, name={self._settings.name}, key={self._identity.get_public_key().hex()[:16]}"
        )
        
        # await self.advertise()
        self.logger.info("Starting tasks")
        for task in self.__tasks:
            task.start(self)

        await self._dispatcher_task
        
    async def stop(self) -> None:
        """Stop the bot."""
        if not self.is_running:
            self.logger.error("Bot is not running! Cannot stop a bot that is not running")
            return
        try:
            self.node.dispatcher.remove_raw_packet_subscriber(self._on_raw_packet_rx_log)
        except Exception:
            self.logger.debug("Remove raw packet subscriber during stop failed", exc_info=True)
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
            self._dispatcher_task = None
        self.node.stop()
        self.logger.info("Bot stopped")
        self._running = False
        
    ####################
    # Background Tasks #
    ####################
    
    async def _advert(self, *args, **kwargs) -> None:
        await self.advertise()
        
    async def _cleanup_cache(self, *args, **kwargs) -> None:
        to_remove = []
        for packet_hex, tstamp in self._packet_cache.items():
            if datetime.now().timestamp() > tstamp + 120:
                to_remove.append(packet_hex)
        for item in to_remove:
            del self._packet_cache[item]
    
    #########################
    # Abstract method impls #
    #########################
    
    async def _send_packet(self, pkt: Packet, wait_for_ack: bool = False) -> bool:
        """Send a packet via the MeshNode dispatcher."""
        return await self.node.dispatcher.send_packet(pkt, wait_for_ack=wait_for_ack)
    
    #####################
    # Handler accessors #
    #####################
    
    def _get_protocol_response_handler(self) -> Any:
        return getattr(self.node.dispatcher, "protocol_response_handler", None)

    def _get_login_response_handler(self) -> Any:
        return getattr(self.node.dispatcher, "login_response_handler", None)

    def _get_text_handler(self) -> Any:
        return getattr(self.node.dispatcher, "text_message_handler", None)
        
    ###############
    # Flood Scope #
    ###############
    
    def set_flood_scope(self, transport_key: Optional[bytes] = None) -> None:
        """Set or clear flood scope and propagate to the dispatcher."""
        super().set_flood_scope(transport_key)
        self.node.dispatcher.flood_transport_key = self._flood_transport_key

    def set_flood_region(self, region_name: Optional[str] = None) -> None:
        """Set flood region and propagate to the dispatcher."""
        super().set_flood_region(region_name)
        self.node.dispatcher.flood_transport_key = self._flood_transport_key

    def set_path_hash_mode(self, mode: int) -> None:
        """Set path hash mode and sync to dispatcher default."""
        super().set_path_hash_mode(mode)
        self.node.dispatcher.set_default_path_hash_mode(self.prefs.path_hash_mode)
        
    ########################
    # Device Configuration #
    ########################
    
    def set_advert_name(self, name: str) -> None:
        self.logger.info(f"Changing name to from {self.node.node_name} to {name}")
        super().set_advert_name(name)
        self.node.node_name = self.prefs.node_name

    def _get_group_text_handler(self):
        """Return the group text handler for name sync."""
        return getattr(self.node.dispatcher, "group_text_handler", None)

    def set_radio_params(self, freq_hz: int, bw_hz: int, sf: int, cr: int) -> bool:
        super().set_radio_params(freq_hz, bw_hz, sf, cr)
        if hasattr(self._radio, "configure_radio"):
            try:
                self._radio.configure_radio( # type: ignore
                    frequency=freq_hz,
                    bandwidth=bw_hz,
                    spreading_factor=sf,
                    coding_rate=cr,
                )
                return True
            except Exception as e:
                self.logger.error(f"Error configuring radio: {e}")
                return False
        return True

    def set_tx_power(self, power_dbm: int) -> bool:
        super().set_tx_power(power_dbm)
        if hasattr(self._radio, "set_tx_power"):
            try:
                self._radio.set_tx_power(power_dbm) # type: ignore
                return True
            except Exception as e:
                self.logger.error(f"Error setting TX power: {e}")
                return False
        return True
    
    ##################
    # Key Management #
    ##################
    
    def import_private_key(self, key: bytes) -> bool:
        try:
            self._identity = LocalIdentity(seed=key)
            self._pending_ack_crcs.clear()
            self.node = MeshNode(
                radio=self._radio,
                local_identity=self._identity,
                config={
                    "node": {"name": self.prefs.node_name},
                    "radio": self._radio_config,
                },
                contacts=self.contacts,
                channel_db=self.channels,
                event_service=self._event_service,
            )
            self._setup_packet_callbacks()
            self.logger.info(f"Imported new identity: {self._identity.get_public_key().hex()[:16]}...")
            return True
        except Exception as e:
            self.logger.error(f"Error importing private key: {e}")
            return False
    
    ##############
    # Statistics #
    ##############
    
    def _get_radio_stats(self) -> dict:
        radio_stats = super()._get_radio_stats()
        if hasattr(self._radio, "get_last_rssi"):
            radio_stats["last_rssi"] = self._radio.get_last_rssi()
        if hasattr(self._radio, "get_last_snr"):
            radio_stats["last_snr"] = self._radio.get_last_snr()
        return radio_stats
    
    def _live_stats(self) -> dict[str, int]:
        return {
            "uptime_sec": (datetime.now() - self._start_time).seconds,
            "packets_sent": self._packets_sent,
            "packets_received": self._packets_received,
        }
        
    ############
    # Handlers #
    ############
    
    def _setup_packet_callbacks(self) -> None:
        dispatcher = self.node.dispatcher
        dispatcher.set_packet_received_callback(self.on_packet_receive)
        dispatcher.set_packet_sent_callback(self.on_packet_send)
        dispatcher.set_ack_received_listener(self._on_ack_received)
        dispatcher.add_raw_packet_subscriber(self._on_raw_packet_rx_log)
        dispatcher.raw_data_received_callback = self._on_raw_custom_received
        
    async def on_packet_receive(self, packet: Packet) -> None:
        self._packets_received += 1
        if packet.get_payload_type() not in [PAYLOAD_TYPE_GRP_TXT, PAYLOAD_TYPE_TXT_MSG]:
            return
        if packet.get_packet_hash_hex() in self._packet_cache:
            return
        self._packet_cache[packet.get_packet_hash_hex()] = datetime.now().timestamp()
        if content := packet.decrypted.get("group_text_data", {}).get("full_content"):
            if content.split(": ")[1].startswith("/"):
                context = Context(self, packet)
                await self.dispatch(context.command, context)
            
    async def on_packet_send(self, packet: Packet) -> None:
        self._packets_sent += 1
            
    async def _on_raw_packet_rx_log(self, packet: Packet, data: bytes, analysis: Any) -> None:
        self.logger.debug(f"Got packet: {packet.get_payload_type()}")
        snr = packet.snr or packet._snr or 0.0
        rssi = packet.rssi or packet._rssi or 0
        await self._fire_callbacks("rx_log_data", snr, rssi, data)
    
    async def _on_ack_received(self, crc: int) -> None:
        await self._try_confirm_send(crc)
        
    async def _on_raw_custom_received(self, packet: Packet) -> None:
        payload = bytes(packet.payload) if packet.payload else b""
        snr = packet.snr or packet._snr or 0.0
        rssi = packet.rssi or packet._rssi or 0
        await self._fire_callbacks("raw_data_received", payload, snr, rssi)
        
    ####################
    # Command Handling #
    ####################
        
    def command(self, callback: CallbackType) -> CallbackType:
        """Create a new command.
        
        Usage:
        ```
        bot = Bot(settings)
        
        @bot.command
        async def ping(ctx):
            await ctx.send("Pong!")
        ```
        
        Args:
            callback: Function to call on command execution
        """
        name = callback.__name__
        self.logger.debug(f"Adding command {self._settings.prefix}{name}")
        self.__commands.append(Command(name, callback))
        return callback
        
    # TODO:
    # - Add validation
    async def dispatch(self, command: str, *args, **kwargs):
        for cmd in self.__commands:
            if cmd.name == command:
                await cmd.callback(*args, **kwargs)
                break
            
    ##################
    # Tasks Handling #
    ##################
    
    def task(self, task: Task) -> Task:
        self.logger.debug(f"Adding task with {task.trigger.__class__.__name__}")
        self.__tasks.append(task)
        return task