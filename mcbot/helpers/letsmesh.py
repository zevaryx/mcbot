import binascii
import json
import logging
import ssl
from base64 import urlsafe_b64encode as b64encode
from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING, Callable

import paho.mqtt.client as mqtt
from nacl.signing import SigningKey
from pymc_core import LocalIdentity
from pymc_core.protocol.utils import PAYLOAD_TYPES

from mcbot.utils.radio import get_radio_str

if TYPE_CHECKING:
    from ..settings import Settings

def b64url(b: bytes):
    return b64encode(b).decode("UTF-8").rstrip("=")

class LetsMeshBroker:
    """LetsMesh Broker (also used for MeshMapper)"""
    
    def __init__(
        self, 
        name: str, 
        host: str, 
        port: int, 
        audience: str, 
        jwt_expiry_minutes: int, 
        use_tls: bool,
        public_key: str, 
        private_key_hex: str,
        seed: str,
        radio_str: str,
        iata: str,
        node_name: str,
        app_version: str,
        status_interval: int = 300,
        owner: str | None = None,
        email: str | None = None,
        live_stats: Callable | None = None,
    ):
        self.name = name
        self.host = host
        self.port = port
        self.audience = audience
        self.jwt_expiry_minutes = jwt_expiry_minutes
        self.use_tls = use_tls
        self.public_key = public_key
        self.private_key_hex = private_key_hex
        self.seed = seed
        self.radio_str = radio_str
        self.iata = iata
        self.node_name = node_name
        self.status_interval = status_interval
        self.owner = owner or ""
        self.email = email or ""
        self.live_stats = live_stats
        
        self.app_version = app_version
        
        self._running = False
        self._connect_time = None
        self._tls_verified = False
        self._status_task = None
        self._logger = logging.getLogger(__name__)
        self.client = mqtt.Client(client_id=f"meshcore_{self.public_key}", transport="websockets")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        
    def _generate_jwt(self) -> str:
        now = datetime.now(tz=UTC)
        headers = {"alg": "Ed25519", "typ": "JWT"}
        
        payload = {
            "publicKey": self.public_key.upper(),
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self.jwt_expiry_minutes)).timestamp()),
        }
        
        if self.use_tls and self._tls_verified and (self.email or self.owner):
            payload["email"] = self.email
            payload["owner"] = self.owner
            self._logger.debug(f"Broker {self.name}: JWT includes email/owner (TLS verified)")
        else:
            payload["email"] = ""
            payload["owner"] = ""
            if not self.use_tls:
                self._logger.debug(f"Broker {self.name}: JWT excludes email/owner (TLS disabled)")
            elif not self._tls_verified:
                self._logger.debug(f"Broker {self.name}: JWT excludes email/owner (TLS not verified yet)")
            else:
                self._logger.debug(f"Broker {self.name}: JWT excludes email/owner (email/owner not configured)")
                
        header_b64 = b64url(json.dumps(headers, separators=(",", ":")).encode())
        payload_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode())
        
        signing_input = f"{header_b64}.{payload_b64}".encode()
        seed32 = binascii.unhexlify(self.seed)
        signer = SigningKey(seed32)
        
        derived_public = binascii.hexlify(bytes(signer.verify_key)).decode()
        if derived_public.upper() != self.public_key.upper():
            raise ValueError(
                f"Broker {self.name}: Public key mismatch! Derived: {derived_public}, Expected: {self.public_key}"
            )
            
        signature = signer.sign(signing_input).signature
        signature_hex = binascii.hexlify(signature).decode()
        token = f"{header_b64}.{payload_b64}.{signature_hex}"
        
        self._logger.debug(f"Broker {self.name}: Generated MeshCore token: {token[:10]}...{token[-10:]}")
        
        return token
    
    #########
    # Setup #
    #########
    
    def _on_connect(self, client: mqtt.Client, userdata, flags, rc: int):
        if rc == 0:
            self._logger.info(f"Connected to {self.name}")
            self._running = True
            
            self.publish_status(
                state="online", origin=self.node_name, radio_config=self.radio_str
            )
            
            # connected start heartbeat thread
            if self.status_interval > 0 and not self._status_task:
                import threading
                self._status_task = threading.Thread(target=self._status_heartbeat_loop, daemon=True)
                self._status_task.start()
                self._logger.info(f"Started status heartbeat (interval: {self.status_interval}s)")
        else:
            self._logger.error(f"Failed with code {rc}")
            
    def _on_disconnect(self, client, userdata, rc):
        self._logger.warning(f"Disconnected (rc={rc})")
        self._running = False
        
    def _refresh_jwt_token(self):
        """Refresh JWT token for MQTT authentication"""
        token = self._generate_jwt()
        username = f"v1_{self.public_key}"
        self.client.username_pw_set(username=username, password=token)
        self._connect_time = datetime.now(UTC)
        self._logger.info("JWT token refreshed")
        
    #######################
    # Connection handlers #
    #######################
    
    def connect(self):
        # Conditional TLS setup
        if self.use_tls:
            # Enable TLS with certificate verification
            self.client.tls_set(
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT
            )
            self.client.tls_insecure_set(False)  # Enforce hostname verification
            # Mark as verified - if connection fails, we won't connect anyway
            self._tls_verified = True
            if self.email or self.owner:
                self._logger.info(f"{self.name}: TLS enabled with certificate verification - email/owner will be included")
            protocol = "wss"
        else:
            protocol = "ws"

        # Generate JWT token (will include email/owner if TLS verified)
        token = self._generate_jwt()
        username = f"v1_{self.public_key}"
        self.client.username_pw_set(username=username, password=token)

        self._logger.info(
            f"Connecting to {self.name} "
            f"({protocol}://{self.host}:{self.port}) ..."
        )

        # Must use raw hostname without wss://
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()
        self._connect_time = datetime.now(UTC)

    def disconnect(self):
        self._running = False
        # Publish offline status before disconnecting
        self.publish_status(state="offline", origin=self.node_name, radio_config=self.radio_str)
        import time

        time.sleep(0.5)  # Give time for the message to be sent

        self.client.loop_stop()
        self.client.disconnect()
        self._logger.info("Disconnected")
        
    def reconnect(self):
        if self._running:
            try:
                self.disconnect()
            except Exception as e:
                self._logger.info(f"Broker {self.name}: Disconnect failed, not fully unexpected, manually running disconnect")
                self._running = False
                self.client.loop_stop()
                self.client.disconnect()
                
        self.connect()

    def _status_heartbeat_loop(self):
        """Background thread that publishes periodic status updates"""
        import time

        while self._running:
            try:
                # Refresh JWT token before it expires (at 80% of expiry time)
                if self._connect_time:
                    elapsed = (datetime.now(UTC) - self._connect_time).total_seconds()
                    expiry_seconds = self.jwt_expiry_minutes * 60
                    if elapsed >= expiry_seconds * 0.8:
                        self._refresh_jwt_token()
                
                self.publish_status(
                    state="online", origin=self.node_name, radio_config=self.radio_str
                )
                self._logger.debug(f"Status heartbeat sent (next in {self.status_interval}s)")
                time.sleep(self.status_interval)
            except Exception as e:
                self._logger.error(f"Status heartbeat error: {e}")
                time.sleep(self.status_interval)
            
    ##################
    # Packet Helpers #
    ##################
    
    def _process_packet(self, pkt: dict) -> dict:
        return {"timestamp": datetime.now(UTC).isoformat(), "origin_id": self.public_key, **pkt}
    
    def _topic(self, subtopic: str) -> str:
        return f"meshcore/{self.iata}/{self.public_key}/{subtopic}"
    
    def publish_packet(self, pkt: dict, subtopic="packets", retain=False) -> mqtt.MQTTMessageInfo:
        return self.publish(subtopic, self._process_packet(pkt), retain)
    
    def publish_raw_data(self, raw_hex: str, subtopic="raw", retain=False) -> mqtt.MQTTMessageInfo:
        pkt = {"type": "raw", "data": raw_hex, "bytes": len(raw_hex) // 2}
        return self.publish_packet(pkt, subtopic, retain)
    
    def publish_status(
        self,
        state: str = "online",
        location: dict | None = None,
        extra_stats: dict | None = None,
        origin: str | None = None,
        radio_config: str | None = None
    ) -> mqtt.MQTTMessageInfo:
        if self.live_stats:
            live_stats = self.live_stats()
        else:
            live_stats = {"uptime_secs": 0, "packets_sent": 0, "packets_received": 0}
            
        status = {
            "status": state,
            "timestamp": datetime.now(UTC).isoformat(),
            "origin": origin or self.node_name,
            "origin_id": self.public_key,
            "model": "MCBot",
            "firmware_version": self.app_version,
            "radio": radio_config or self.radio_str,
            "client_version": f"mcbot/{self.app_version}",
            "stats": {**live_stats, "errors": 0, "queue_len": 0, **(extra_stats or {})}
        }
        
        if location:
            status["location"] = location
            
        return self.publish("status", status, retain=False)
        
            
    def publish(self, subtopic: str, payload: dict, retain: bool = False) -> mqtt.MQTTMessageInfo:
        if not self._running:
            self._logger.warning(f"Broker {self.name}: Disconnected, attempting to reconnect...")
            self.reconnect()
        topic = self._topic(subtopic)
        message = json.dumps(payload)
        result = self.client.publish(topic, message, retain=retain)
        if result.rc > 0:
            self._logger.error(f"Broker {self.name}: Publish failed, attempting to reconnect and publish again")
            self.reconnect()
            result = self.client.publish(topic, message, retain=retain)
        self._logger.debug(f"Broker {self.name}: Publish result: {result.rc=}")
        self._logger.debug(f"Broker {self.name}: Published to {topic}: {message}")
        return result
            
    

class LetsMeshHelper:
    def __init__(self, settings: Settings, identity: LocalIdentity, seed: str, app_version: str, live_stats: Callable | None = None):
        if not settings.letsmesh:
            raise ValueError("LetsMesh configuration missing")
        elif not settings.letsmesh.enabled:
            raise ValueError("LetsMesh is disabled, not configuring")
        elif not settings.letsmesh.iata:
            raise ValueError("IATA required for LetsMesh MQTT broker, not configuring")
        
        self.settings = settings
        self.radio_str = get_radio_str(self.settings)
        self.live_stats = live_stats
        self.public_key = identity.get_public_key().hex()
        self.private_key_hex = identity.get_private_key().hex()
        self.seed = seed
        self.brokers = [
            LetsMeshBroker(
                **x.model_dump(), 
                app_version=app_version,
                public_key=self.public_key, 
                private_key_hex=self.private_key_hex,
                seed=self.seed,
                radio_str=self.radio_str,
                iata=settings.letsmesh.iata,
                node_name=settings.name,
                live_stats=self.live_stats,
                status_interval=settings.letsmesh.status_interval,
            ) for x in settings.letsmesh.brokers
        ]
    
    ############
    # Adapters #
    ############
    
    def connect(self):
        for broker in self.brokers:
            broker.connect()
            
    def disconnect(self):
        for broker in self.brokers:
            broker.disconnect()
    
    def publish_packet(self, pkt: dict, subtopic="packets", retain=False) -> list[mqtt.MQTTMessageInfo]:
        return [x.publish(subtopic, pkt, retain) for x in self.brokers]
    
    def publish_raw_data(self, raw_hex: str, subtopic="raw", retain=False) -> list[mqtt.MQTTMessageInfo]:
        return [x.publish_raw_data(raw_hex, subtopic, retain) for x in self.brokers]
    
    def publish_status(
        self,
        state: str = "online",
        location: dict | None = None,
        extra_stats: dict | None = None,
        origin: str | None = None,
        radio_config: str | None = None
    ) -> list[mqtt.MQTTMessageInfo]:
        return [x.publish_status(state, location, extra_stats, origin, radio_config) for x in self.brokers]
            
    def publish(self, subtopic: str, payload: dict, retain: bool = False) -> list[mqtt.MQTTMessageInfo]:
        return [x.publish(subtopic, payload, retain) for x in self.brokers]
        