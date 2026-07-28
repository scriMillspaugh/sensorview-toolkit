# Labeling practices

How the tools in this repo validate device and zone labels, and the naming format
they recommend. Two separate things — the validator **enforces** a short list of
hard rules, and **suggests** a format you are free to ignore.

---

## Part 1 — What is enforced

A label that breaks any of these is refused. The write never happens.

### Character rules

Labels become BACnet `Object_Name` values, so they follow BACnet's restrictions:

- **Start with a letter.** Never a digit.
- **Letters, digits, underscores, and hyphens only** — `A–Z`, `a–z`, `0–9`, `_`, `-`.
- **No spaces.** They break automated network scripts.
- **No symbols** — `%`, `&`, `#`, `$`, `@`, `?` and friends. (`$` is a common habit
  carried over from electrical drawings; it has to go.)
- **No slashes.** `/` and `\` get mistaken for directory paths.
- **No math operators** — `+`, `*`, `=`.
- **No accents or non-ASCII glyphs.** They cause encoding errors downstream.

Case is not enforced. Uppercase (`LOBBY_01_PP`) and CamelCase (`ChilledWaterTemp`)
are both fine — pick one and stay consistent.

### Length

**Devices ≤ 20 characters. Zones ≤ 50 characters.**

These come from the SensorView database itself, not from BACnet. The columns in
`sensor.mdb` are:

| Column | Type |
|---|---|
| `Devices.UserLabelCurrent`, `Devices.UserLabelAuthority` | `VARCHAR(20)` |
| `Devices.DisplayNameCurrent`, `Devices.DisplayNameAuthority` | `VARCHAR(20)` |
| `Zones.ZoneName`, `Zones.ZoneNameCurrent` | `VARCHAR(50)` |

BACnet is far more permissive — 255 characters maximum, with under 50 the usual
safe practice and 32 the limit on some legacy controllers. SensorView is the
tighter constraint, so SensorView is what the validator uses.

**This matters because Access fails silently.** Writing an over-length label
raises no error; the value is simply cut to fit:

```
device: wrote 30 chars -> stored 20
zone:   wrote 70 chars -> stored 50
```

Nothing tells you it happened. Worse, truncation can manufacture duplicates —
two labels that differ only after the cutoff collapse into one. Validating before
the write is the only protection.

### Uniqueness

**No duplicate labels.** Devices and zones are checked separately, so a device and
a zone may share a name. Duplicates within either group collide as BACnet points.

---

## Part 2 — Recommended practice

Everything below is a **suggestion**. The validator may emit a note about it; a
note never blocks anything. If your site already has a working convention, keep it.

This format is offered because it survives contact with a BMS: it sorts sensibly,
parses mechanically, and stays inside the 20-character device budget.

### Structure

```
Zone    {BLDG}_{FLR}_{AREA}
Device  {BLDG}_{FLR}_{ROOM}_{TYPE}_{SEQ}
```

| Field | Rule | Example |
|---|---|---|
| `BLDG` | Short building token, consistent across the site | `B1` |
| `FLR` | Two characters, zero-padded — `01`–`12`, `P1`, `PH` | `08` |
| `ROOM` / `AREA` | Room number, or a cardinal for open areas | `135`, `N` |
| `TYPE` | Device type code (table below) | `PPE` |
| `SEQ` | Two digits, per room and per type | `01` |

Zone examples:

```
B1_10_135        enclosed room  — AREA is the room number
B1_08_N_01       open office    — AREA is a cardinal direction
B1_12_GFX_01     graphics/control group
```

Device example:

```
B1_10_135_PPE_01    emergency power pack, room 135
```

### Exceptions

- **Gateways and bridges** omit the area descriptor: `{BLDG}_{FLR}_{TYPE}[_{SEQ}]`.
- **Eclypse controllers** are one per floor and take no sequence — `B1_04_ECY`.
- **Site-level controllers** use `Site` in place of the floor token — `B1_Site_ECY`.

### Device type codes

Load-switching, by load type:

| Code | Device |
|---|---|
| `PP` | Power pack — normal lighting |
| `PPE` | Power pack — emergency / life-safety |
| `PPL` | Power pack — plug load |
| `SP` | Switch/dimmer pack — normal lighting |
| `SPE` | Switch/dimmer pack — emergency |
| `PC` | Photocell — normal |
| `PCE` | Photocell — emergency |

Sensors and user devices:

| Code | Device |
|---|---|
| `OS` | Occupancy sensor, PIR |
| `OSPDT` | Occupancy sensor, dual-tech |
| `OSDL` | Occupancy + daylight |
| `WS` | Wall switch with occupancy sensor |
| `KP` | Keypad, standard |
| `KPT` | Keypad, touchscreen |
| `KPG` | Keypad, graphics |

Infrastructure:

| Code | Device |
|---|---|
| `RP` | Room panel |
| `IO` | I/O module |
| `BRG` | Bridge |
| `GWY` | Gateway |
| `ECY` | Eclypse controller |

### Underscore or hyphen?

Both pass validation. **Underscores are recommended** — Acuity's nLight
documentation specifies the underscore as the separator, while BACnet itself
accepts either. Using a hyphen produces an advisory note, not an error.

### A parsing trap worth knowing

If you derive floors and rooms from *existing* labels, watch for bare room numbers
with no floor prefix. A label like `816_PP` fed to a greedy `\d{1,2}` floor pattern
reads as "floor 81, room 6". Trust the device's parent bridge or gateway topology
for the floor instead, and sanity-check that every floor you derive is one the
building actually has.

The validator's floor-token note exists to catch exactly this. It fires whenever
the second underscore-separated field isn't a recognized floor — which is also
what happens when you use a different naming scheme entirely, so treat it as a
prompt to look, not a defect.
