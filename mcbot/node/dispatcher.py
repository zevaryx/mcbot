"""Monkey patching to remove odd logging in pyMC_core"""

import asyncio
from typing import Optional

from pymc_core import Packet
from pymc_core.protocol.utils import format_packet_info
from pymc_core.node.dispatcher import PH_TYPE_SHIFT, Dispatcher as pyMC_Dispatcher, PathUtils

class Dispatcher(pyMC_Dispatcher):
    async def _process_received_packet(
        self,
        data: bytes,
        rssi: Optional[int] = None,
        snr: Optional[float] = None,
    ) -> None:
        """Process received packet. rssi/snr are per-packet when provided."""
        self._logger.debug(f"[RX DEBUG] Processing packet: {len(data)} bytes, data: {data.hex()[:32]}...")

        # Notify raw RX subscribers so clients can track repeats
        if rssi is not None:
            rssi_val = rssi
        elif hasattr(self.radio, "get_last_rssi"):
            rssi_val = self.radio.get_last_rssi()
        else:
            rssi_val = 0
        if snr is not None:
            snr_val = snr
        elif hasattr(self.radio, "get_last_snr"):
            snr_val = self.radio.get_last_snr()
        else:
            snr_val = 0.0
        for cb in self._raw_rx_subscribers:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data, rssi_val, snr_val)
                else:
                    cb(data, rssi_val, snr_val)
            except Exception as e:
                self._logger.debug(f"Raw RX subscriber error: {e}")

        # Blacklist check uses raw-frame hash (catches known-bad bytes before parsing)
        raw_hash = self.packet_filter.generate_hash(data)
        if self.packet_filter.is_blacklisted(raw_hash):
            self._logger.debug("[RX DEBUG] Packet blacklisted, skipping")
            return

        # Parse before dedup — calculate_packet_hash() needs a parsed packet
        pkt = Packet()
        try:
            pkt.read_from(data)
            self._logger.debug("[RX DEBUG] Packet parsed successfully")
        except Exception as err:
            self._logger.debug(f"Malformed packet: {err}")
            self.packet_filter.blacklist(raw_hash)
            self._logger.debug(f"Blacklisted malformed packet (raw hash: {raw_hash})")
            return

        # Packets at max hops for their path encoding must not be retransmitted
        if PathUtils.is_path_at_max_hops(pkt.path_len):
            pkt.mark_do_not_retransmit()

        ptype = pkt.header >> PH_TYPE_SHIFT

        self._logger.debug(f"[RX DEBUG] Packet type: {ptype:02X}")

        # Use per-packet rssi/snr when provided (avoids race); else fall back to radio last values
        pkt._rssi = rssi if rssi is not None else self.radio.get_last_rssi()
        pkt._snr = snr if snr is not None else self.radio.get_last_snr() # type: ignore

        # Let the node know about this packet for analysis (statistics, caching, etc.)
        if self.packet_analysis_callback:
            try:
                if asyncio.iscoroutinefunction(self.packet_analysis_callback):
                    await self.packet_analysis_callback(pkt, data)
                else:
                    self.packet_analysis_callback(pkt, data)
                self._logger.debug("[RX DEBUG] Packet analysis callback completed")
            except Exception as e:
                self._logger.error(f"Error in packet analysis callback: {e}")

        # Notify raw packet subscribers (e.g. companion clients for PUSH_CODE_LOG_RX_DATA)
        # This fires BEFORE dedup so the UI sees all path variants for logging
        analysis = {}
        for callback in self._raw_packet_subscribers:
            await self._invoke_enhanced_raw_callback(callback, pkt, data, analysis)
        if self.raw_packet_callback:
            await self._invoke_enhanced_raw_callback(self.raw_packet_callback, pkt, data, {})
        if self._raw_packet_subscribers or self.raw_packet_callback:
            self._logger.debug("[RX DEBUG] Raw packet callback completed")

        # Dedup uses payload-based hash (matches firmware), ignoring path differences
        # Only blocks handler dispatch — UI/logging subscribers above still see all variants
        packet_hash = pkt.calculate_packet_hash().hex()[:16]
        if self.packet_filter.is_duplicate(packet_hash):
            self._logger.debug(f"Duplicate packet ignored (hash: {packet_hash})")
            return
        self.packet_filter.track_packet(packet_hash)

        # Check if this is our own packet before processing handlers
        if self._is_own_packet(pkt):
            packet_info = format_packet_info(pkt.header, len(pkt.payload))

            self._logger.debug(f"OWN PACKET RECEIVED! {packet_info}")
            self._logger.debug(
                "   This suggests your packet was repeated by another node and came back to you!"
            )
            self._logger.debug(f"Ignoring own packet (type={pkt.header >> 4:02X}) to prevent loops")
            return

        # Handle ACK matching for waiting senders
        self._logger.debug("[RX DEBUG] Dispatching packet to handlers")
        await self._dispatch(pkt)