from dataclasses import dataclass
from typing import TYPE_CHECKING

from pymc_core.protocol.packet import Packet

from mcbot.models.internal.commands import CommandType, Command

if TYPE_CHECKING:
    from mcbot.client import Bot, PrefixedCommand

class Context:
    def __init__(self, bot: Bot, packet: Packet, cmd_type: CommandType):
        self.bot = bot
        self.packet = packet
        self.type = packet.get_payload_type()
        self.data = packet.decrypted.get("group_text_data")
        if not self.data:
            raise ValueError("Invalid packet")
        self.sender: str = self.data.get("sender_name")
        self.full_content = ": ".join(self.data.get("full_content").split(": ")[1:])
        cmd = self.full_content.split(" ")[0]
        if cmd_type == CommandType.PREFIXED:
            cmd = cmd.split("/")[1]
        self.command: Command = self.bot.get_command(cmd, cmd_type=cmd_type) # type: ignore
        self.content = cmd.join(self.full_content.split(cmd)[1:]).strip()
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
        self.bot.set_path_hash_mode(self.packet.get_path_hash_size() - 1)
        await self.bot.send_channel_message(self.channel, text) # type: ignore
        