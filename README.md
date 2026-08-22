# Home Assistant integration for Biamp Tesira

Controls a Biamp Tesira DSP over SSH using the Tesira Text Protocol (TTP).
Exposes configured presets to Home Assistant as push buttons, and
configured Level Control blocks as `number` entities (dB faders), polled
so external changes on the Tesira show up in Home Assistant too.

Built against Biamp Cornerstone's official "Tesira Text Protocol" manual
(v4.2, Dec 2021) and the current TTP reference tables at
[tesira-help.biamp.com](https://tesira-help.biamp.com/System_Control/Tesira_Text_Protocol/Overview.htm).

## How presets work

TTP has **no command that lists all presets** in a design (no
`getPresetList` or equivalent — confirmed against both the v4.2 manual and
the current online reference). There's no way to enumerate presets over
the wire, so you tell Home Assistant which preset names to expose, and
each becomes a push button that calls:

```
DEVICE recallPresetByName "<name>"
```

The name must match the preset's name in the Tesira project exactly
(case- and spelling-sensitive).

## How level controls work

Each Level Control block in a Tesira design is addressed by its Instance
Tag and a channel number (channel 1 for a single-channel block). You give
the integration the tag (and channel, if not 1) and it creates a `number`
entity — a dB slider — backed by:

```
<tag> get level <channel>       # read on every poll
<tag> set level <channel> <dB>  # write when moved in Home Assistant
```

The slider's min/max are read once from the block's own `minLevel` /
`maxLevel` attributes at startup, not hardcoded to Tesira's absolute
-100 to +12 dB limits, so it matches whatever range was configured in
the design. When you add a level control in the config/options flow, the
integration immediately tries to read its value to confirm the tag (and
channel) are actually a Level Control block — Leveler, Compressor, and
other dynamics blocks look similar but don't expose a `level` attribute
and will be rejected at that point rather than failing silently later.

Every level control is polled every 10 seconds (`DEFAULT_LEVEL_POLL_INTERVAL`
in `const.py`) so a change made directly on the Tesira — another control
system, the front panel, Tesira software — is reflected in Home Assistant
within that window. TTP does support push-style `subscribe`, which would
update faster and with less SSH traffic, but polling was chosen instead
for simplicity and to avoid managing subscription state across
reconnects.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → Custom repositories → add this repo URL,
   category "Integration".
2. Install "Biamp Tesira", restart Home Assistant.

### Manual

Copy `custom_components/tesira` into your Home Assistant `custom_components`
directory and restart.

## Setup

Settings → Devices & Services → Add Integration → "Biamp Tesira". You'll
need:

- Host/IP of the Tesira
- SSH port (default 22)
- Username / password (unprotected systems default to `default` / `default`;
  the account needs at least *controller* level to recall presets)

The integration keeps one persistent SSH session open to the device and
serializes commands over it (TTP is a stateful line protocol, not
request-scoped), reconnecting automatically if the session drops.

Once the connection test succeeds, setup continues straight into adding
presets — enter each preset's exact name, add as many as you like, then
*Done* to finish. You don't have to add any at this point; presets can
always be added or removed later too.

### Adding presets or level controls later

Settings → Devices & Services → Biamp Tesira → Configure. Same menu as
during setup: *Add a preset* (name only), *Add a level control* (Instance
Tag + channel), and the matching *Remove* options. Changes take effect
immediately — the integration reloads automatically when options change.

## Notes from testing against a real device

Validated end-to-end against a live TesiraFORTE — SSH
login with `default`/`default`, the TTP shell session itself, a real
`recallPresetByName` call, and `get level`/`get minLevel`/`get maxLevel`
against several real Level Control blocks (`ProgramLevel`, `SubLevel`,
`Level3`). One thing that isn't documented: the SSH channel needs a PTY
allocated, or the device accepts the connection and banner then silently
drops it the instant a command is sent. The client requests one
(`term_type="dumb"`) for this reason.

Also confirmed live: pointing the level-control validation at a Leveler
block instead of a Level Control block (`Leveler1`) correctly fails with
`-ERR 'level' is not supported by LevelerInterface::Attributes` — exactly
the case the add-level config step's validation is meant to catch.

## Known limitations

- Only one TTP command is in flight at a time per config entry (by design —
  TTP responses aren't tagged with a request ID, so commands are
  serialized to keep them correlated).
- If a preset name doesn't exist in the Tesira project, pressing its
  button surfaces a Home Assistant error (from `-ERR`) rather than
  failing silently.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest tests/
```

### Testing against a real device

```bash
.venv/bin/python scripts/test_connection.py \
    --host 10.0.0.5 --username default --password default

# also recall a preset by name:
.venv/bin/python scripts/test_connection.py \
    --host 10.0.0.5 --recall "Morning Announcement"

# read one or more Level Control blocks (repeatable, TAG or TAG:CHANNEL):
.venv/bin/python scripts/test_connection.py \
    --host 10.0.0.5 --get-level ProgramLevel --get-level "Zone 2 Volume:1"
```

Credentials can also come from `TESIRA_HOST` / `TESIRA_USERNAME` /
`TESIRA_PASSWORD` / `TESIRA_PORT` environment variables instead of flags.
