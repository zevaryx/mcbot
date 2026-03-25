import asyncio
import inspect
import logging
from hashlib import sha256
from datetime import datetime, timedelta
from time import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from pymc_core import LocalIdentity
from pymc_core.companion.companion_base import CompanionBase, Contact, MeshEvents
from pymc_core.companion.constants import (
    ADV_TYPE_CHAT,
    DEFAULT_MAX_CHANNELS,
    DEFAULT_MAX_CONTACTS,
    DEFAULT_OFFLINE_QUEUE_SIZE,
)
from pymc_core.node.node import MeshNode
from pymc_core.protocol.constants import (
    PAYLOAD_TYPE_ADVERT,
    PAYLOAD_TYPE_GRP_TXT,
    PAYLOAD_TYPE_TXT_MSG,
)
from pymc_core.protocol.packet import Packet
from pymc_core.protocol.packet_utils import PacketHeaderUtils

from mcbot.const import __version__
from mcbot.helpers.letsmesh import LetsMeshHelper
from mcbot.helpers.sqlite import SQLiteHelper
from mcbot.models.internal.command import Command, CallbackType
from mcbot.models.internal.context import Context
from mcbot.models.internal.packet import PacketRecord
from mcbot.models.internal.task import Task
from mcbot.models.internal.triggers import IntervalTrigger, TimeTrigger
from mcbot.utils.board_configs import HARDWARE_CONFIGS
from mcbot.utils.identity import create_or_load_identity, get_seed
from mcbot.utils.radio import create_radio

if TYPE_CHECKING:
    from mcbot.settings import Settings

class Bot(CompanionBase):
    node: MeshNode
    name: str
    sqlite: SQLiteHelper | None
    
    _logger: logging.Logger
    _settings: Settings
    _identity: LocalIdentity
    _packet_cache: dict[str, float]
    _start_time: datetime
    _dispatcher_task: Optional[asyncio.Task]
    _packets_sent: int
    _packets_received: int
    _letsmesh: LetsMeshHelper | None
    _disallowed_packet_types: list[str]    
    _commands: list[Command]
    _tasks: list[Task]
    
    __lock: asyncio.Lock
    
    def __init__(self, settings: Settings):
        self.name = settings.name
        try:
            self.sqlite = SQLiteHelper(settings)
        except Exception:
            self._logger.warning("SQLite not configured, skipping")
        
        self.__lock = asyncio.Lock()
        
        logging.basicConfig(level=settings.logging.level, format=settings.logging.format)
        self._logger = logging.getLogger(__name__)
        logging.debug(f"Creating bot with name {self.name}")
        self._settings = settings
        self._identity = create_or_load_identity(self._settings.identity)
        self._radio, self._radio_config = create_radio(self._settings)
        self._logger.info(f"Radio in use: {HARDWARE_CONFIGS[self._settings.hardware]['name']}")
        self._logger.info(f"Frequency info: freq={self._radio_config['frequency']}")
        self._commands: list[Command] = []
        self._tasks: list[Task] = []
        self._packet_cache: dict[str, float] = {}
        self._disallowed_packet_types = []
        if self._settings.letsmesh:
            self._disallowed_packet_types = self._settings.letsmesh.disallowed_packet_types
        
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
        try:
            self._letsmesh = LetsMeshHelper(self._settings, self._identity, get_seed(), __version__, self._live_stats)
        except Exception as e:
            self._logger.warning(f"LetsMesh not enabled. Reason: {e}")
        
        self.task(Task(self._cleanup_cache, IntervalTrigger(minutes=5)))
        self.task(Task(self._advert, TimeTrigger(hour=12)))
        self.task(Task(self._advert, TimeTrigger(hour=0)))
        if self._settings.letsmesh:
            self.task(Task(self._publish_status, IntervalTrigger(seconds=self._settings.letsmesh.status_interval)))
        
    @property
    def is_running(self) -> bool:
        return self._running
    
    ############
    # Lifespan #
    ############
    
    async def start(self):
        """Start the bot."""
        if self.is_running:
            self._logger.warning("Bot is already running!")
            return
        
        advert = False
        
        self._logger.info("Starting bot!")
        if self.sqlite:
            self._logger.debug("Loading contacts from sqlite")
            await self.sqlite._init_db()
            contacts = await self.sqlite.load_contacts()
            for contact in contacts:
                self.add_update_contact(contact)
            last_advert = await self.sqlite.get_last_advert()
            now = datetime.now()
            if datetime.fromtimestamp(last_advert) + timedelta(hours=12) <= datetime.now():
                advert = True
                await self.sqlite.update_advert(int(now.timestamp()))
                
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
                    self._logger.error(f"No secret provided for channel: {channel.name}")
                    continue
                else:
                    self._logger.error(f"Unknown channel type: {channel.type}")
                    continue
            secret = bytes.fromhex(secret)
            self._logger.debug(f"Adding channel {channel.name}...")
            if not self.set_channel(idx=idx+1, name=channel.name, secret=secret):
                self._logger.error(f"Failed to create channel: {channel.name}")
        
        self._running = True
        self._start_time = datetime.now()
        if self._letsmesh:
            self._letsmesh.connect()
        
        self.node.dispatcher.set_default_path_hash_mode(self.prefs.path_hash_mode)
        self._dispatcher_task = asyncio.create_task(self.node.start())
        self._logger.info(
            f"Bot started, name={self._settings.name}, key={self._identity.get_public_key().hex()[:16]}"
        )
        if advert:
            await self._advert()
        
        # await self.advertise()
        self._logger.info("Starting tasks")
        for task in self._tasks:
            task.start(self)
            
        await self._publish_status()

        await self._dispatcher_task
        
    async def stop(self) -> None:
        """Stop the bot."""
        if not self.is_running:
            self._logger.error("Bot is not running! Cannot stop a bot that is not running")
            return
        try:
            self.node.dispatcher.remove_raw_packet_subscriber(self._on_raw_packet_rx_log)
        except Exception:
            self._logger.debug("Remove raw packet subscriber during stop failed", exc_info=True)
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
            self._dispatcher_task = None
        self.node.stop()
        self._logger.info("Bot stopped")
        self._running = False
        
    ####################
    # Background Tasks #
    ####################
    
    async def _publish_status(self, *args, **kwargs) -> None:
        if self._letsmesh:
            self._logger.debug("Sending LetsMesh status update")
            result = self._letsmesh.publish_status()
            result_data = [
                {
                    "rc": x.rc,
                    "is_published": x.is_published(),
                } for x in result
            ]
            self._logger.debug(f"Publish status result: {result_data}")
    
    async def _advert(self, *args, **kwargs) -> None:
        # We need to lock while we advert because we change hash mode a few times
        async with self.__lock:
            for i in range(3):
                self.set_path_hash_mode(i)
                await self.advertise()
            self.set_path_hash_mode(None)
        
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

    def set_path_hash_mode(self, mode: int | None) -> None:
        """Set path hash mode and sync to dispatcher default."""
        super().set_path_hash_mode(mode) # type: ignore
        self.node.dispatcher.set_default_path_hash_mode(self.prefs.path_hash_mode)
        
    ########################
    # Device Configuration #
    ########################
    
    def set_advert_name(self, name: str) -> None:
        self._logger.info(f"Changing name to from {self.node.node_name} to {name}")
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
                self._logger.error(f"Error configuring radio: {e}")
                return False
        return True

    def set_tx_power(self, power_dbm: int) -> bool:
        super().set_tx_power(power_dbm)
        if hasattr(self._radio, "set_tx_power"):
            try:
                self._radio.set_tx_power(power_dbm) # type: ignore
                return True
            except Exception as e:
                self._logger.error(f"Error setting TX power: {e}")
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
            self._logger.info(f"Imported new identity: {self._identity.get_public_key().hex()[:16]}...")
            return True
        except Exception as e:
            self._logger.error(f"Error importing private key: {e}")
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
        packet_record = self.create_packet_record(packet)
        self.record_packet(packet_record)
        
        if packet.get_packet_hash_hex() in self._packet_cache:
            return
        
        self._packet_cache[packet.get_packet_hash_hex()] = datetime.now().timestamp()
        if packet.get_payload_type() not in [PAYLOAD_TYPE_GRP_TXT, PAYLOAD_TYPE_TXT_MSG]:
            return
        
        if self.node.dispatcher._is_own_packet(packet):
            return
        
        if content := packet.decrypted.get("group_text_data", {}).get("full_content"):
            if content.split(": ")[1].startswith("/"):
                context = Context(self, packet)
                await self.dispatch(context.command, context)
            
    async def on_packet_send(self, packet: Packet) -> None:
        self._packets_sent += 1
        self._packet_cache[packet.get_packet_hash_hex()] = datetime.now().timestamp()
            
    async def _on_raw_packet_rx_log(self, packet: Packet, data: bytes, analysis: Any) -> None:
        self._logger.debug(f"Got packet: {packet.get_payload_type()}")
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
        
    def record_packet(self, packet_record: dict, skip_letsmesh_if_invalid: bool = True):
        self._logger.debug(
            f"Recording packet: type={packet_record.get('type')}, "
            f"transmitted={packet_record.get('transmitted')}"
        )
        
        if skip_letsmesh_if_invalid and (reason := packet_record.get("drop_reason")):
            self._logger.debug(f"Skipping LetsMesh publish for packet with drop_reason: {reason}")
        else:
            self._publish_to_letsmesh(packet_record)
            
    def _publish_to_letsmesh(self, packet_record: dict):
        if not self._letsmesh:
            return
        
        try:
            packet_type = packet_record.get("type")
            if packet_type is None:
                self._logger.error("Cannot publish to LetsMesh: packet_record missing 'type' field")
                return

            if packet_type in self._disallowed_packet_types:
                self._logger.debug(f"Skipped publishing packet type 0x{packet_type:02X} (disallowed)")
                return

            node_name = self._settings.name
            packet = PacketRecord.from_packet_record(
                packet_record, origin=node_name, origin_id=self._letsmesh.public_key
            )

            if packet:
                self._letsmesh.publish_packet(packet.to_dict())
                self._logger.debug(f"Published packet type 0x{packet_type:02X} to LetsMesh")
            else:
                self._logger.debug("Skipped LetsMesh publish: packet missing raw_packet data")

        except Exception as e:
            self._logger.error(f"Failed to publish packet to LetsMesh: {e}", exc_info=True)
            
    async def _handle_mesh_event(self, event_type: str, data: dict) -> None:
        try:
            now = int(time())
            if event_type == MeshEvents.NEW_MESSAGE:
                await self._handle_new_message(data)
            elif event_type == MeshEvents.NEW_CHANNEL_MESSAGE:
                await self._handle_new_channel_message(data)
            elif event_type == MeshEvents.NEW_CONTACT:
                await self._fire_callbacks("node_discovered", data)
            elif event_type == MeshEvents.CONTACT_UPDATED:
                pass
            elif event_type == MeshEvents.NODE_DISCOVERED:
                # Advert pipeline (single path): all adverts applied here; one event
                # -> one store update and at most one advert_received (Bridge and Radio).
                contact = Contact.from_dict(data, now=now)
                if len(contact.public_key) >= 7 and contact.name:
                    inbound_path = data.get("inbound_path")
                    path_len_encoded = data.get("path_len_encoded")
                    applied = await self._apply_advert_to_stores(
                        contact, inbound_path, path_len_encoded=path_len_encoded
                    )
                    if applied is not None:
                        if self.sqlite:
                            await self.sqlite.save_contact(applied)
                        await self._fire_callbacks("advert_received", applied)
                await self._fire_callbacks("node_discovered", data)
            elif event_type == MeshEvents.TELEMETRY_UPDATED:
                await self._fire_callbacks("telemetry_response", data)
        except Exception as e:
            self._logger.error(f"Error handling mesh event {event_type}: {e}")
        
    ####################
    # Command Handling #
    ####################
        
    def command(
        self,
        name: str = "", 
        description: str = "", 
        help: str = ""
    ) -> Callable[[CallbackType], Command]:
        """Create a new command.
        
        Usage:
        ```
        bot = Bot(settings)
        
        @bot.command(description="Pong!")
        async def ping(ctx):
            await ctx.send("Pong!")
        ```
        
        Args:
            callback: Function to call on command execution
        """
        def wrapper(func: CallbackType) -> Command:
            if not inspect.iscoroutinefunction(func):
                raise ValueError("Commands must be coroutines!")
            
            _name = name or func.__name__
            _description = description or func.__doc__ or "No description"
            _help = description or help or self._settings.prefix + _name
            cmd = Command(_name, func, _description, _help)
            self._logger.debug(f"Adding command {self._settings.prefix}{name}")
            self._commands.append(cmd)
            return cmd
        return wrapper
        
    # TODO:
    # - Add validation
    async def dispatch(self, command: str, *args, **kwargs):
        for cmd in self._commands:
            if cmd.name == command:
                self._logger.debug(f"Dispatching command: {command}")
                try:
                    async with self.__lock:
                        await cmd.callback(*args, **kwargs)
                except Exception as e:
                    self._logger.error(f"Command {command} failed: {e}", exc_info=True)
                break
            
    ##################
    # Tasks Handling #
    ##################
    
    def task(self, task: Task) -> Task:
        self._logger.debug(f"Adding task with {task.trigger.__class__.__name__}")
        self._tasks.append(task)
        return task
    
    ###########
    # Helpers #
    ###########
    
    @staticmethod
    def calculate_packet_score(snr: float, packet_len: int, spreading_factor: int = 8) -> float:

        # SNR thresholds per SF (from MeshCore RadioLibWrappers.cpp)
        snr_thresholds = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}

        if spreading_factor < 7:
            return 0.0

        threshold = snr_thresholds.get(spreading_factor, -10.0)

        # Below threshold = no chance of success
        if snr < threshold:
            return 0.0

        # Success rate based on SNR above threshold
        success_rate_based_on_snr = (snr - threshold) / 10.0

        # Collision penalty: longer packets more likely to collide (max 256 bytes)
        collision_penalty = 1.0 - (packet_len / 256.0)

        # Combined score
        score = success_rate_based_on_snr * collision_penalty

        return max(0.0, min(1.0, score))
    
    def create_packet_record(self, packet: Packet) -> dict[str, Any]:
        if not hasattr(packet, "header") or packet.header is None:
            self._logger.error(f"Packet missing header attribute! Packet: {packet}")
            payload_type = 0
            route_type = 0
        else:
            header_info = PacketHeaderUtils.parse_header(packet.header)
            payload_type = header_info["payload_type"]
            route_type = header_info["route_type"]
            self._logger.debug(
                f"Packet header=0x{packet.header:02x}, type={payload_type}, route={route_type}"
            )
            
        snr = packet.snr or packet._snr or 0.0
        rssi = packet.rssi or packet._rssi or 0
        transmitted = False
        tx_delay_ms = 0.0
        drop_reason = None
        original_path = list(packet.path) if packet.path else []
        pkt_hash = packet.get_packet_hash_hex()
        is_dupe = pkt_hash in self._packet_cache
        
        path_hash = None
        display_path = (
            original_path if original_path else (list(packet.path) if packet.path else [])
        )
        if display_path and len(display_path) > 0:
            # Format path as array of uppercase hex bytes
            path_bytes = [f"{b:02X}" for b in display_path[:8]]  # First 8 bytes max
            if len(display_path) > 8:
                path_bytes.append("...")
            path_hash = "[" + ", ".join(path_bytes) + "]"

        src_hash = None
        dst_hash = None

        # Payload types with dest_hash and src_hash as first 2 bytes
        if payload_type in [0x00, 0x01, 0x02, 0x08]:
            if hasattr(packet, "payload") and packet.payload and len(packet.payload) >= 2:
                dst_hash = f"{packet.payload[0]:02X}"
                src_hash = f"{packet.payload[1]:02X}"

        # ADVERT packets have source identifier as first byte
        elif payload_type == PAYLOAD_TYPE_ADVERT:
            if hasattr(packet, "payload") and packet.payload and len(packet.payload) >= 1:
                src_hash = f"{packet.payload[0]:02X}"


        packet_record = {
            "timestamp": time(),
            "header": (
                f"0x{packet.header:02X}"
                if hasattr(packet, "header") and packet.header is not None
                else None
            ),
            "payload": (
                packet.payload.hex() if hasattr(packet, "payload") and packet.payload else None
            ),
            "payload_length": (
                len(packet.payload) if hasattr(packet, "payload") and packet.payload else 0
            ),
            "type": payload_type,
            "route": route_type,
            "length": len(packet.payload or b""),
            "rssi": rssi,
            "snr": snr,
            "score": self.calculate_packet_score(
                snr, len(packet.payload or b""), self._settings.radio.spreading_factor
            ),
            "tx_delay_ms": tx_delay_ms,
            "transmitted": transmitted,
            "is_duplicate": is_dupe,
            "packet_hash": pkt_hash[:16],
            "drop_reason": drop_reason,
            "path_hash": path_hash,
            "src_hash": src_hash,
            "dst_hash": dst_hash,
            "original_path": ([f"{b:02X}" for b in original_path] if original_path else None),
            "forwarded_path": None,
            "raw_packet": packet.write_to().hex() if hasattr(packet, "write_to") else None,
        }
        
        return packet_record