# Home Assistant integration for Biamp Tesira

Controls a Biamp Tesira DSP over SSH using the Tesira Text Protocol (TTP),
and exposes configured presets to Home Assistant as push buttons.

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

### Adding preset buttons later

Settings → Devices & Services → Biamp Tesira → Configure → *Add a preset*,
enter the preset's exact name. Each preset creates one button entity.
Remove presets from the same menu; changes take effect immediately (the
integration reloads automatically when options change).

## Notes from testing against a real device

Validated end-to-end against a live TesiraFORTE — SSH
login with `default`/`default`, and the TTP shell session itself. One
thing that isn't documented: the SSH channel needs a PTY allocated, or
the device accepts the connection and banner then silently drops it the
instant a command is sent. The client requests one (`term_type="dumb"`)
for this reason.

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
```

Credentials can also come from `TESIRA_HOST` / `TESIRA_USERNAME` /
`TESIRA_PASSWORD` / `TESIRA_PORT` environment variables instead of flags.
