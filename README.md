# Home Assistant integration for Biamp Tesira

Controls a Biamp Tesira DSP over SSH using the Tesira Text Protocol (TTP).
Exposes configured presets to Home Assistant as push buttons, and
configured Level Control blocks as `number` entities (dB faders) that
stay live via TTP's push-based subscribe mechanism — no polling, so
changes made on the Tesira itself show up in Home Assistant within a
fraction of a second.

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
<tag> subscribe level <channel> <token> <throttle_ms>  # once, when the entity is added
<tag> set level <channel> <dB>                         # write when moved in Home Assistant
```

There's no `get`/polling involved at runtime at all. TTP's `subscribe`
command asks the device to push an unsolicited line every time the value
changes:

```
! "publishToken":"<token>" "value":<dB>
```

These arrive interleaved with ordinary command responses on the same SSH
session, tagged with a `!` prefix and the token given at subscribe time
(one per entity, derived from its Instance Tag). The client runs a
background reader task that continuously reads lines and routes each one
either to whichever command is currently waiting for its response, or —
for `!` lines — to the matching entity's callback, which updates Home
Assistant state directly. A `throttle_ms` (default 250ms, see
`DEFAULT_LEVEL_SUBSCRIBE_THROTTLE_MS` in `const.py`) caps how often
pushes are sent while a value is changing continuously, e.g. during a
fader ramp.

Subscriptions are session state on the Tesira and are lost on any
reconnect, so the client tracks every active subscription and re-sends
them all as soon as a new session is established — including after an
automatic reconnect (see below), with no action needed from the entity.

The slider's min/max are read once via a plain `get minLevel`/`get
maxLevel` at startup, not hardcoded to Tesira's absolute -100 to +12 dB
limits, so it matches whatever range was configured in the design. When
you add a level control in the config/options flow, the integration
immediately tries a plain `get level` to confirm the tag (and channel)
are actually a Level Control block — Leveler, Compressor, and other
dynamics blocks look similar but don't expose a `level` attribute and
will be rejected at that point rather than failing silently later.

### Reconnection

If the SSH session drops, the client detects it (the background reader
task hits EOF) and retries in the background with exponential backoff
(5s, 10s, 20s ... capped at 60s) until it reconnects, at which point every
active subscription is automatically re-armed. A `number` entity reports
itself unavailable while disconnected (it has no confirmed value to
show), and comes back automatically once a push arrives on reconnect —
no manual reload needed. Button presses and level writes that happen to
race a drop get one immediate reconnect-and-retry of their own, rather
than waiting for the background retry loop.

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

The `subscribe` push pipeline was validated live too: subscribing to
`ProgramLevel` and then moving its fader by hand (Tesira software) produced
a real-time stream of `!`-prefixed push messages on the same SSH session
as ordinary command traffic, correctly throttled to roughly one update
per 250-500ms rather than one per DSP tick, with a clean `+OK` on
unsubscribe.

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

# subscribe and print push updates for 20s (move the fader externally to test):
.venv/bin/python scripts/test_connection.py \
    --host 10.0.0.5 --subscribe ProgramLevel --subscribe-seconds 20

# or set a level directly and confirm it took:
.venv/bin/python scripts/test_connection.py \
    --host 10.0.0.5 --set-level ProgramLevel=-20
```

Credentials can also come from `TESIRA_HOST` / `TESIRA_USERNAME` /
`TESIRA_PASSWORD` / `TESIRA_PORT` environment variables instead of flags.
