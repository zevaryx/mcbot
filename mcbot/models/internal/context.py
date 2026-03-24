from dataclasses import dataclass
from typing import TYPE_CHECKING

from pymc_core.protocol.packet import Packet

if TYPE_CHECKING:
    from mcbot.client import Bot

class Context:
    def __init__(self, bot: Bot, packet: Packet):
        self.bot = bot
        self.packet = packet
        self.type = packet.get_payload_type()
        self.data = packet.decrypted.get("group_text_data")
        if not self.data:
            raise ValueError("Invalid packet")
        self.sender: str = self.data.get("sender_name")
        self.content = ": ".join(self.data.get("full_content").split(": ")[1:])
        self.command = self.content.split("/")[1].split(" ")[0]
        self.channel_name = self.data.get("channel_name")
        self.channel = self.bot.channels.find_by_name(self.channel_name)
        if not self.channel:
            raise ValueError("Could not find channel!")
        
    async def reply(self, text: str):
        full_text = f"@[{self.sender}] {text}"
        if len(full_text) > 140:
            raise ValueError("Length of text + sender name cannot exceed 140 characters")
        await self.send(f"@[{self.sender}] {text}")
        
    async def send(self, text: str):
        if len(text) > 140:
            raise ValueError("Length of text cannot exceed 140 characters")
        await self.bot.send_channel_message(self.channel, text) # type: ignore
        