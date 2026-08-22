# Home Assistant integration for Biamp Tesira

Controls a Biamp Tesira DSP over SSH using the Tesira Text Protocol (TTP),
and exposes its presets to Home Assistant as push buttons.

Built against Biamp Cornerstone's official "Tesira Text Protocol" manual
(v4.2, Dec 2021) and the current TTP reference tables at
[tesira-help.biamp.com](https://tesira-help.biamp.com/System_Control/Tesira_Text_Protocol/Overview.htm).

## Important: how preset discovery actually works

TTP has **no command that lists all presets** in a design (no
`getPresetList` or equivalent — confirmed against both the v4.2 manual and
the current online reference). The only presets this integration can see
are:

1. **Preset Button blocks** (auto-discovered). Each Preset Button block in
   your Tesira design is a named Instance Tag with a `preset` attribute
   holding the preset ID it's wired to. On startup and every 5 minutes,
   the integration runs `SESSION get aliases` to list every Instance Tag,
   then sends `<tag> get preset 1` to each one — any tag that answers is
   treated as a discovered preset, using the tag name as the button's
   name and the returned ID as the preset to recall.

   **To expose a preset this way**, add a Preset Button block to your
   Tesira design for it, and name the block's Instance Tag whatever you
   want the Home Assistant button to be called.

2. **Manually configured presets** (fallback). For presets you don't want
   to wire up a Preset Button block for, add them by hand from the
   integration's *Configure* options: a name, and optionally a numeric
   preset ID. If you leave the ID blank, the button recalls by name
   (`DEVICE recallPresetByName`) instead of by ID.

Recalling always goes through the DEVICE service commands
(`DEVICE recallPreset <id>` / `DEVICE recallPresetByName "<name>"`) —
the Preset Button block's own attribute is only ever read, never written,
so this integration can't accidentally reprogram which preset a button
points to.

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

### Adding presets without a Preset Button block

Settings → Devices & Services → Biamp Tesira → Configure → *Add a preset*.

## Notes from testing against a real device

Validated end-to-end against a live TesiraFORTE (login, discovery, and
listing all Instance Tags). One thing that isn't documented: the SSH
channel needs a PTY allocated, or the device accepts the connection and
banner then silently drops it the instant a command is sent. The client
requests one (`term_type="dumb"`) for this reason.

## Known limitations

- If a Preset Button block is later removed from the design, its Home
  Assistant button becomes unavailable rather than disappearing from the
  entity registry — it isn't auto-removed.
- Only one TTP command is in flight at a time per config entry (by design —
  TTP responses aren't tagged with a request ID, so commands are
  serialized to keep them correlated).
- Tested against a local Tesira for the connection/discovery/recall paths
  described above; TTP subscription-based features are not used or needed
  here.

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
```

This connects, lists every Instance Tag, probes for Preset Button blocks,
and prints what it found. Pass `--recall <preset_id>` to also trigger a
recall. Credentials can also come from `TESIRA_HOST` / `TESIRA_USERNAME` /
`TESIRA_PASSWORD` / `TESIRA_PORT` environment variables instead of flags.
