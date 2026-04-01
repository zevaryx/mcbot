import logging
from typing import Any, Optional

from pymc_core import LocalIdentity
from pymc_core.node.node import MeshNode as pyMC_node

from mcbot.node.dispatcher import Dispatcher

class MeshNode(pyMC_node):
    def __init__(
        self,
        radio: Optional[Any],
        local_identity: LocalIdentity,
        config: Optional[dict] = None,
        *,
        contacts: Optional[Any] = None,
        channel_db: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
        event_service: Optional[Any] = None,
    ) -> None:
        """Initialise a mesh network node instance.

        Args:
            radio: Radio hardware interface for transmission/reception.
            local_identity: Node's cryptographic identity for secure communication.
            config: Optional configuration dictionary with node settings.
            contacts: Optional contact storage for managing known nodes.
            channel_db: Optional channel database for group communication.
            logger: Optional logger instance; defaults to module logger.
            event_service: Optional event service for broadcasting mesh events.
        """
        self.radio = radio
        self.identity = local_identity
        self.contacts = contacts  # App can inject contact storage
        self.channel_db = channel_db  # App can inject channel database
        self.event_service = event_service  # App can inject event service

        # Node name should be provided by app
        self.node_name = config.get("node", {}).get("name", "unknown") if config else "unknown"
        self.radio_config = config.get("radio", {}) if config else {}

        self.logger = logger or logging.getLogger("MeshNode")
        self.log = self.logger

        # App-injected analysis components
        self.packet_filter = None

        self.dispatcher = Dispatcher(radio, log_fn=self.log.info, packet_filter=self.packet_filter)

        # Set contact book for decryption
        self.dispatcher.set_contact_book(self.contacts)
        self.dispatcher.register_default_handlers(
            contacts=self.contacts,
            local_identity=self.identity,
            channel_db=self.channel_db,
            event_service=self.event_service,
            node_name=self.node_name,
            radio_config=self.radio_config,
        )