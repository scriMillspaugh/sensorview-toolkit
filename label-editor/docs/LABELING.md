# Labeling practices

How the tools in this repo validate device and zone labels, and the naming format
they recommend. Two separate things — the validator **enforces** a short list of
hard rules, and **suggests** a format you are free to ignore.

---

## Part 1 — What is enforced

A label that breaks any of these is refused. The write never happens.

### Character rules

Labels become BACnet `Object_Name` values through the nLight ECLYPSE controller,
so they follow BACnet's restrictions plus Acuity's tighter nLight rules:

- **Start with a letter.** Never a digit.
- **Letters, digits, and underscores only** — `A–Z`, `a–z`, `0–9`, `_`.
- **No hyphens.** BACnet on its own would accept `-`, but Acuity's nLight BMS
  integration rules allow the underscore only. (`-` is a common habit from
  electrical drawings, like `$`; both have to go.)
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

### IDs in the rename list

**Every ID must be one the backup actually has.** An `UPDATE` against an ID that
matches nothing fails silently, so the IDs are checked before anything is written:

- **An ID that looks damaged by Excel blocks the whole run** — see the next section.
- **An ID that is simply not in this backup** (a device removed since the list was
  made) is skipped and listed. It is never counted as a change.

### Editing the CSV in Excel

Excel decides for itself which columns are numbers, and it gets nLight device IDs
wrong in two ways — **silently, on open, before you edit anything**:

| Original ID | What Excel saves | Recoverable? |
|---|---|---|
| `381E0024` (hex that looks like a number) | `3.81E+26` | **No** — the digits are gone |
| `02319041` (all digits) | `2319041` | Only by guessing the zeros back |

Opening the template in Excel and saving it is enough to do this. On a 4,336-device
site it damaged 329 IDs — 63 in scientific notation, 266 missing leading zeros — and
the damaged rows looked like new devices.

The tools refuse a CSV with damaged IDs and say which ones. To edit the list in Excel
without the damage:

1. Open a blank workbook. Do **not** double-click the CSV.
2. **Data → From Text/CSV** → pick the file → **Transform Data**.
3. Select the `DeviceID` column → **Data Type → Text** → **Replace current**.
4. **Close & Load**, edit, then **Save As → CSV UTF-8**.

Or skip Excel: any text editor, or the table in the web tool, leaves the IDs alone.
If a CSV is already damaged, download a fresh template — a damaged ID cannot be
repaired from the file itself.

Excel's **CSV UTF-8** format starts the file with an invisible byte-order mark. Both
tools read it correctly.

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

**Underscore.** Since 1.3.0 a hyphen is refused, not just flagged — see Part 1.
Versions 1.1.0–1.2.0 accepted hyphens with an advisory note, because BACnet allows
them; Acuity's nLight rules do not, and the stricter rule is the one that decides
whether the BMS can read the point. Labels already in your system are not affected
until you rename them.

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
