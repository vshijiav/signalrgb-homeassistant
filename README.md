# SignalRGB for Home Assistant — WebPipe edition

**English** | [简体中文](README.zh-CN.md)

Control [SignalRGB](https://signalrgb.com) from Home Assistant **without a SignalRGB Pro
subscription**.

This is a modified version of
[hyperb1iss/signalrgb-homeassistant](https://github.com/hyperb1iss/signalrgb-homeassistant).
The original talks to SignalRGB's HTTP API (port 16038), which only answers Pro users. This
version talks to the local channel the SignalRGB desktop UI itself uses, so everything the
free app can do from its own window can be done from Home Assistant.

## What's different from upstream

| | Upstream 1.x | This version (2.x) |
| --- | --- | --- |
| SignalRGB plan | Pro required | Free works |
| Transport | HTTP API on `:16038` | WebPipe QWebChannel on `127.0.0.1:16036`, via a small relay |
| Updates | Polling every 5 minutes | Pushed instantly (`local_push`) |
| Power / brightness | Global canvas toggle (Pro API) | Per-device brightness on every device and component |
| Current effect | Light attribute only | Effect select, plus one entity per effect parameter |
| Extra | — | Effect rotation switch and interval, Windows `srgb` CLI |

## How it works

```
Home Assistant ──WebSocket──▶ webpipe_relay.py on the PC (:16046) ──▶ SignalRGB WebPipe (127.0.0.1:16036)
```

The SignalRGB desktop app publishes its core objects (lighting, devices, layouts, ...) over a
[QWebChannel](https://doc.qt.io/qt-6/qtwebchannel-javascript.html) WebSocket named
**WebPipe**. Its own UI drives the app through it, with no Pro check. WebPipe only listens on
localhost, so `windows/webpipe_relay.py` forwards it to your LAN and accepts only the IPs you
allow.

- **Effects**: `lighting.setAlwaysEffect(name)`, the same call the app's UI makes. Next,
  previous and random map to `goForward()`, `goBackward()` and `goCrazy()`.
- **Power and brightness**: every lighting endpoint (each device and each component on a
  controller channel) has a writable `Brightness`. *Off* sets all of them to 0 and remembers
  each one's level; *on* restores those levels. The running effect never changes.
- **Effect parameters**: the running effect's parameter model is read with `itemList()`, and
  each parameter's `value` is written directly. SignalRGB rebuilds these objects while an
  effect loads, so the integration subscribes to the model's change signals and re-reads it.

## Requirements

- SignalRGB on Windows (free plan is fine). Tested with **2.5.82**.
- Python 3.11+ on the same PC, for the relay. Only the standard library is used.
- Home Assistant **2026.4** or newer. Tested with **2026.9.4**.

## Installation

### 1. Run the relay on the SignalRGB PC

Copy [`windows/webpipe_relay.py`](windows/webpipe_relay.py) to the PC and start it, allowing
your Home Assistant host's IP:

```powershell
python webpipe_relay.py --allow 192.168.1.10
```

- `--allow` is required and can be repeated. Connections from any other IP are refused.
- `--port` changes the LAN port (default `16046`).
- The relay logs to `webpipe_relay.log` next to the script.
- Allow inbound TCP on the port in Windows Firewall if Windows asks, or if Home Assistant
  can't connect.

To start it in the background at every logon, register a scheduled task (run once, in
PowerShell; adjust the script path and IP):

```powershell
$py = (Get-Command python).Source
$script = 'C:\path\to\webpipe_relay.py'
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\conhost.exe" -Argument "--headless `"$py`" -I `"$script`" --allow 192.168.1.10" -WorkingDirectory (Split-Path $script)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'SignalRGB WebPipe relay' -Action $action -Settings $settings -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
Start-ScheduledTask -TaskName 'SignalRGB WebPipe relay'
```

- `conhost --headless` runs `python.exe` without a console window. It keeps the program
  `python.exe`, so a firewall rule you already allowed for Python applies (`pythonw.exe` is a
  different program to Windows Firewall).
- `-ExecutionTimeLimit 0` matters: by default Windows stops scheduled tasks after 72 hours.
- If the relay exits with an error, the task restarts it after a minute.

Give the PC a fixed IP (a DHCP reservation) so Home Assistant can always find it.

### 2. Install the integration

#### With HACS (recommended)

1. **HACS → ⋮ (top right) → Custom repositories**
2. Repository: `https://github.com/vshijiav/signalrgb-homeassistant`, type: **Integration** → **Add**
3. Open **SignalRGB (WebPipe edition)** in HACS → **Download**, then restart Home Assistant.

HACS then follows this repository's releases, so updates come from this version and not from
upstream.

> **Already have the upstream integration from HACS?** Both use the `signalrgb` domain, so
> stop HACS tracking the upstream one first. Don't use HACS's *Remove* on it if you want to
> keep your config entry: removing deletes `custom_components/signalrgb`. Downloading this
> version over it is enough; afterwards ignore any update HACS offers for the upstream entry.

#### Manually

Copy `custom_components/signalrgb/` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

### 3. Add it in Home Assistant

**Settings → Devices & Services → Add Integration → SignalRGB**, then enter the PC's IP and
the relay port (`16046`).

## Entities

| Entity | What it does |
| --- | --- |
| `light.signalrgb_*` | On/off and brightness for all devices; the effect list is every installed effect |
| `select.*_effect` | The running effect; pick another to switch |
| `select.*_layout` | Saved SignalRGB layouts |
| `select.*_effect_preset` | Saved presets of the running effect (unavailable when it has none) |
| `button.*_next_effect` / `_previous_effect` / `_random_effect` | Navigate effects |
| `switch.*_effect_rotation` | Rotate effects on SignalRGB's timer |
| `number.*_effect_rotation_interval` | Seconds between rotations (minimum 10) |
| Effect parameters | One entity per parameter of the running effect (see below) |

**Effect parameters** follow the running effect. Each parameter becomes an entity the first
time an effect that has it runs:

| SignalRGB parameter | Entity |
| --- | --- |
| Slider / hue | `number` (slider, with the effect's min, max and step) |
| On/off | `switch` |
| Drop-down | `select` |
| Color | `text` (`#rrggbb`) |

Parameters that the running effect doesn't have are hidden automatically and shown again
when an effect that uses them runs. Entities you hide yourself are left alone.

## Windows command-line tool

[`windows/srgb.cmd`](windows/srgb.cmd) controls SignalRGB from a terminal or a scheduled
task, using the same WebPipe channel:

```powershell
srgb status          # on (Aurora)
srgb off             # remember the effect, switch to the off effect
srgb on              # restore the remembered effect
srgb toggle
srgb effect "Aurora"
```

- `off` switches to an installed "lights off" effect. The default is `AA关灯`; pass
  `-OffEffect "Good Night!"` (or any other effect) to use a different one.
- `status` reads the current effect through SignalRGB's built-in MCP server, so keep
  **Settings → Application → AI Integration → Model Context Protocol** enabled.
- State (the remembered effect) is kept in `state.json` next to the script.

## Security

WebPipe exposes the whole app, including your signed-in SignalRGB account details. The relay
only forwards connections from the IPs you pass with `--allow`. Never forward the relay port
to the internet.

## Limitations

- WebPipe is SignalRGB's internal UI channel, not a public API. A SignalRGB update can rename
  or change the objects this integration uses.
- "Off" dims every device to 0 rather than disabling SignalRGB's canvas; the effect keeps
  running at zero brightness.
- The relay has to be running on the PC. Home Assistant reconnects automatically when it or
  SignalRGB comes back.

## Development

```bash
uv sync
uv run pytest
uv run ruff check custom_components tests
```

The tests run the client against a fake QWebChannel server, so SignalRGB isn't needed.

## Credits and license

Based on [hyperb1iss/signalrgb-homeassistant](https://github.com/hyperb1iss/signalrgb-homeassistant)
by Stefanie Jane, licensed under Apache 2.0. The WebPipe transport, new entities and Windows
tools were added in this version; see [NOTICE](NOTICE) and [CHANGELOG](CHANGELOG.md).

Apache License 2.0, see [LICENSE](LICENSE).

Not affiliated with WhirlwindFX or SignalRGB. It only uses features the free SignalRGB app
offers in its own window.
