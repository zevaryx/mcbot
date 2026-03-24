# mcbot

A Meshcore bot framework designed for use with Raspberry Pi hats

## Requirements

- A Raspberry Pi 4B (or similar) SBC
- A compatible SX1262 LoRa Hat/adapter
  - See [board configs](mcbot/utils/board_configs.py)

## Prerequisites

> [!CAUTION]
> This section assumes you are on a Raspberry Pi. 
> For other boards, please see your manufacturer's instructions on how to enable SPI

### Enable SPI

1. Run `sudo raspi-config`
   1. Go to `Interface Options`
   2. Select `SPI`
   3. Choose `Enable`
2. Run `sudo reboot`

## Adding to your project

Until pyMC_core pushes a release with the `feat/companion` branch included, you will need to directly reference this repo in your requirements/dependencies.

### `pyproject.toml`

```toml
dependencies = [
  "mcbot@git+https://github.com/zevaryx/mcbot.git",
]
```

### `requirements.txt`

```
mcbot @ git+https://github.com/zevaryx/mcbot@main
```

## Basic Usage

```py
import asyncio
from mcbot import Bot, load_settings

settings = load_settings()

bot = Bot(settings)

@bot.command
async def ping(ctx):
  await ctx.reply("Pong!")


asyncio.run(bot.start())
```

See [examples](examples/) for more examples

## Example `config.yaml`

Place in your bot directory, or specify a path when calling `load_settings`

```yaml
---
name: mcbot

# See mcbot/utils/board_configs.py
hardware: waveshare

# Command prefix
prefix: /

# 32-byte seed. Use https://github.com/zevaryx/meshcore-utils to generate a vanity seed,
# or `openssl rand -hex 32` for a random seed
# Alternatively, leave this commented out for the bot to create one on first launch
# (saved to $HOME/.config/mcbot/identity.key)
# DO NOT use the example below
# identity: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

# Frequency settings. Below is the US default preset, please use your region's frequency information
radio:
  # Frequency, in mHz
  frequency: 910.525
  
  # Bandwidth, in kHz
  bandwidth: 62.5
  spreading_factor: 7
  coding_rate: 5

# Channels to listen to
# Channel types:
#   - hashtag: No secret needs to be defined (but can be!), the secret is derived from the name of the channel
#   - private: Secret needs to be defined
channels:
  - name: "#mcbot"
    type: hashtag

  - name: "Meshcore Bot"
    type: private
    secret: adb501d3653248ca796763f06db04f7a

# Configure LetsMesh (or MeshMapper) MQTT
letsmesh:

  # Whether or not to enable LetsMesh/MeshMapper
  enabled: true

  # Replace with your IATA, i.e. DEN, LAX, etc
  iata: TEST

  # How often to upload status intervals
  status_interval: 300

  # What packet types to disallow
  disallowed_packet_types: []

  # Which brokers to use
  brokers:
    
    # LetsMesh Europe
    - name: Europe (LetsMesh v1)
      host: mqtt-eu-v1.letsmesh.net
      port: 443
      audience: mqtt-eu-v1.letsmesh.net
      jwt_expiry_minuets: 10
      use_tls: true
      owner:
      email:

    # LetsMesh US
    - name: US West (LetsMesh v1)
      host: mqtt-us-v1.letsmesh.net
      port: 443
      audience: mqtt-us-v1.letsmesh.net
      jwt_expiry_minuets: 10
      use_tls: true
      owner:
      email:

    # MeshMapper
    - name: Meshmapper
      host: mqtt.meshmapper.cc
      port: 443
      audience: mqtt.meshmapper.cc
      jwt_expiry_minuets: 10
      use_tls: true
      owner:
      email:

# SQLite storage path for contact storage
sqlite:
  path: storage.db

# Logging configuration. Optional
logging:
  level: INFO
  format: "[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
```

## Future plans

See [TODO.md](TODO.md)