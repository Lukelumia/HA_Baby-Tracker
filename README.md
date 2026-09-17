# Baby Tracker for Home Assistant

A custom integration that reads your own data out of the
[Baby Tracker](https://nighp.com/babytracker/) (Nighp Software) app through its
cloud sync API.

> Status: **scaffold only.** The integration installs and its config flow opens,
> but it does not talk to the API and creates no entities yet. The `TODO`
> markers in the source point at what still has to be filled in.

## Installation

### HACS

1. Add this repository as a custom repository (category: *Integration*).
2. Install **Baby Tracker** and restart Home Assistant.

### Manual

Copy `custom_components/babytracker` into your Home Assistant `config/custom_components`
directory and restart Home Assistant.

## Configuration

Settings → Devices & services → Add integration → **Baby Tracker**, then sign in
with the email address and password of your Baby Tracker account.

## Development

The repository uses [uv](https://docs.astral.sh/uv/) for the development
environment. `uv` installs the right Python itself, so this is the whole setup:

```bash
uv sync                          # creates .venv and resolves uv.lock
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Development dependencies live in the `dev` dependency group in `pyproject.toml`;
`pytest-homeassistant-custom-component` pins the Home Assistant version the tests
run against. The integration's *runtime* requirements are not managed here — they
belong in `custom_components/babytracker/manifest.json`, and Home Assistant
installs them itself (it uses uv for that too).

The reverse-engineered sync protocol this integration is built on is documented
separately; the short version:

| | |
| --- | --- |
| Base URL | `https://prodapp.babytrackers.com` |
| Auth | session cookie from `POST /session` |
| Data | `GET /account/device`, then `GET /account/transaction/{deviceUUID}/{lastSyncID}` |

Read-only: the integration should never upload transactions, to avoid corrupting
the app's own merge state.

## Disclaimer

Not affiliated with or endorsed by Nighp Software. Use with your own account only.
