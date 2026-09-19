# Baby Tracker for Home Assistant

A custom integration that reads your own data out of the
[Baby Tracker](https://nighp.com/babytracker/) (Nighp Software) app through its
cloud sync API and exposes it as sensors you can build a dashboard on.

It is **read-only**: it logs in, replays the account's transaction log locally
and never uploads anything, so it cannot disturb the app's own merge state.

## Installation

### HACS

1. HACS → ⋮ → *Custom repositories* → add
   `https://github.com/Lukelumia/HA_Baby-Tracker` with category *Integration*.
2. Install **Baby Tracker** and restart Home Assistant.

HACS installs the `babytracker.zip` asset from the latest
[release](https://github.com/Lukelumia/HA_Baby-Tracker/releases), so it picks up
tagged versions rather than whatever is on `main`.

### Manual

Copy `custom_components/babytracker` into your Home Assistant
`config/custom_components` directory and restart Home Assistant.

### Removal

Settings → Devices & services → **Baby Tracker** → ⋮ → *Delete*. The stored sync
state is deleted with the entry, and the device this integration registered on
your Baby Tracker account can be removed from the app itself.

## Configuration

Settings → Devices & services → Add integration → **Baby Tracker**, then sign in
with the email address and password of your Baby Tracker account. There is
nothing else to configure; if the password ever changes, Home Assistant asks for
the new one.

## Devices and entities

One device per baby, hanging off a device that represents the account. Entities
are created for the kinds of record your account actually holds — log your first
bath months from now and its sensors appear at the next refresh — except for a
handful of core ones that always exist.

Every `last_*` sensor is a timestamp; the decoded record is on its attributes
(`status`, `amount_ml`, `duration`, `note`, …), so a dashboard card can show
"2 h ago — 150 mL" from a single entity.

### Per baby

| key | name | unit | created |
| --- | --- | --- | --- |
| `last_feed` | Last feed | timestamp | always |
| `last_nursing` | Last nursing | timestamp | when logged |
| `last_bottle` | Last bottle | timestamp | always |
| `last_formula` | Last formula | timestamp | when logged |
| `last_pumped` | Last expressed milk | timestamp | when logged |
| `last_other_feed` | Last other feed | timestamp | when logged |
| `last_diaper` | Last diaper | timestamp | always |
| `last_wet_diaper` | Last wet diaper | timestamp | when logged |
| `last_dirty_diaper` | Last dirty diaper | timestamp | when logged |
| `last_sleep` | Last sleep | timestamp | always |
| `last_bath` | Last bath | timestamp | when logged |
| `last_growth` | Last growth entry | timestamp | when logged |
| `last_temperature` | Last temperature entry | timestamp | when logged |
| `last_medication` | Last medication | timestamp | when logged |
| `last_milestone` | Last milestone | timestamp | when logged |
| `last_vaccine` | Last vaccination | timestamp | when logged |
| `last_journal` | Last journal entry | timestamp | when logged |
| `last_joy` | Last joy | timestamp | when logged |
| `last_other_activity` | Last other activity | timestamp | when logged |
| `feed_today` | Feeds today | — | always |
| `nursing_today` | Nursings today | — | when logged |
| `bottle_today` | Bottles today | — | always |
| `diaper_today` | Diapers today | — | always |
| `wet_diaper_today` | Wet diapers today | — | when logged |
| `dirty_diaper_today` | Dirty diapers today | — | when logged |
| `sleep_today` | Sleeps today | — | always |
| `bath_today` | Baths today | — | when logged |
| `medication_today` | Medications today | — | when logged |
| `last_bottle_amount` | Last bottle amount | mL | when logged |
| `bottle_volume_today` | Bottle volume today | mL | when logged |
| `last_nursing_duration` | Last nursing duration | min | when logged |
| `nursing_duration_today` | Nursing time today | min | when logged |
| `last_sleep_duration` | Last sleep duration | min | when logged |
| `sleep_duration_today` | Sleep today | h | always |
| `last_diaper_status` | Last diaper status | enum | when logged |
| `weight` | Weight | kg | when logged |
| `length` | Length | cm | when logged |
| `head_circumference` | Head circumference | cm | when logged |
| `temperature` | Body temperature | °C | when logged |
| `age` | Age | days | always |

Plus a **Sleeping** binary sensor (a `Sleep` record whose start + duration has
not passed yet) and a **Photo** image entity when the baby has one.

*Feed* covers nursing and every kind of bottle; *bottle* covers formula,
expressed milk and other feeds. A `Mixed` diaper counts as both wet and dirty.

### Per account

| key | name | unit | created |
| --- | --- | --- | --- |
| `last_pump` | Last pumping | timestamp | when logged |
| `pump_today` | Pumpings today | — | when logged |
| `pump_volume_today` | Pumped volume today | mL | when logged |
| `last_sync` | Last sync | timestamp | always (diagnostic) |
| `records` | Stored records | — | always (diagnostic) |
| `sync_devices` | Devices in sync group | — | always (diagnostic) |

Pumping belongs to the account rather than to a baby: a `Pump` record carries no
baby, which is how the app stores it.

## Action

`babytracker.refresh` syncs immediately instead of waiting for the next poll.

```yaml
action: babytracker.refresh
data:
  config_entry_id: <your entry>
  full: false        # true replays the whole history, ignoring the cursors
```

## How the data is kept up to date

Every two minutes the integration asks each device in your sync group for the
transactions after the cursor it last saw. The first sync downloads the account's
whole history; afterwards each poll is a handful of near-empty responses. The
replayed records and the cursors are stored in `.storage`, so a Home Assistant
restart resumes where it left off rather than re-downloading everything.

Counts and totals ending in `_today` are per local calendar day and reset at
midnight. `sleep_duration_today` counts only the part of each nap that has
actually happened today, so a nap running over midnight is split correctly.

## Known limitations

- Values are read from the cloud, so an entry made in the app shows up within a
  poll interval, not instantly.
- The `timezone` field on a record is unreliable (it ignores DST), so times are
  handled as UTC and converted with Home Assistant's own timezone.
- Measurements are converted to metric from whatever unit the writing device
  used; imperial users get conversion back through Home Assistant.
- A baby deleted in the app leaves its device behind in Home Assistant.
- Photos are fetched once and cached until the account points at a new one.

## Dashboard example

```yaml
type: entities
title: Sam
entities:
  - entity: sensor.sam_last_feed
    secondary_info: last-changed
  - sensor.sam_feeds_today
  - sensor.sam_bottle_volume_today
  - entity: sensor.sam_last_diaper
    secondary_info: last-changed
  - sensor.sam_diapers_today
  - binary_sensor.sam_sleeping
  - sensor.sam_sleep_today
  - sensor.sam_weight
```

## Development

The repository uses [uv](https://docs.astral.sh/uv/) for the development
environment. `uv` installs the right Python itself, so this is the whole setup:

```bash
uv sync                          # creates .venv and resolves uv.lock
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

```bash
# Loads the integration into the current Home Assistant release, the way a
# HACS install would. CI runs this weekly to catch upstream breakage.
uv run --no-project --python 3.14 --with homeassistant python scripts/smoke_test.py
```

Development dependencies live in the `dev` dependency group in `pyproject.toml`;
`pytest-homeassistant-custom-component` pins the Home Assistant version the tests
run against. The integration has no *runtime* requirements — the API client is
vendored in `custom_components/babytracker/api.py` and uses only `aiohttp`,
which Home Assistant already ships.

### Layout

| file | what it holds |
| --- | --- |
| `api.py` | the cloud client and the wire-format decoding; no Home Assistant imports |
| `models.py` | turns the replayed records into the per-baby view the entities read |
| `coordinator.py` | polling, plus persistence of the cursors and records |
| `entity.py` | the base entity and the device layout |
| `sensor.py`, `binary_sensor.py`, `image.py` | the platforms |
| `services.py` | the `refresh` action |
| `brand/` | the integration's icon, served locally by Home Assistant 2026.3+ |

The reverse-engineered sync protocol this is built on, in short:

| | |
| --- | --- |
| Base URL | `https://prodapp.babytrackers.com` |
| Auth | session cookie from `POST /session` |
| Data | `GET /account/device`, then `GET /account/transaction/{deviceUUID}/{lastSyncID}` |
| Payload | base64 JSON, polymorphic on a `BCObjectType` discriminator |

The Android and iOS clients serialise differently — iOS writes booleans as the
strings `"true"` / `"false"` and enums as ordinals — so every scalar off the wire
is coerced explicitly in `api.py`.

## Disclaimer

Not affiliated with or endorsed by Nighp Software. Use with your own account only.

## Releasing

Tag a commit on `main` and push the tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

The *Release* workflow stamps `manifest.json` with the version from the tag,
zips `custom_components/babytracker` into `babytracker.zip` and publishes a
GitHub release with that asset — which is what HACS installs.
