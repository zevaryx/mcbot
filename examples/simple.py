import asyncio
from datetime import datetime

from mcbot import triggers, Bot, Context, Task, load_settings

settings = load_settings()

bot = Bot(settings)

@bot.command
async def ping(ctx: Context):
    await ctx.reply("Pong!")
    
@bot.command
async def test(ctx: Context):
    path = ",".join(ctx.packet.get_path_hashes_hex()) or "direct"
    snr = ctx.packet.snr
    rssi = ctx.packet.rssi
    received_at = datetime.now().strftime("%H:%M:%S")
    
    await ctx.send(f"ack @[{ctx.sender}] | {path} | SNR: {snr:.2f} dB | RSSI: {rssi} dBm | Received at: {received_at}")

@bot.task
@Task.create(triggers.IntervalTrigger(minutes=5))
async def five_minute_test(bot: Bot):
    bot.logger.info("5 minutes")
    
asyncio.run(bot.start())