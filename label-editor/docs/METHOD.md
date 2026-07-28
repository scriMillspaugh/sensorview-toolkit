# Method: batch-relabeling nLight devices via a SensorView backup

This documents the approach behind the tool — how a SensorView backup is taken
apart, relabeled, and rebuilt so the new names import cleanly. Written for
anyone (integrator, facility team, or Acuity support) who wants to understand
or reproduce the process.

## 1. The file format

A SensorView **`.svdb` backup is a 7-zip archive** containing a single file,
`sensor.mdb` — a Microsoft Access (JET4) database holding the device tree,
zones, users, and settings.

Tables and columns that matter for labeling:

| Table | Columns | Notes |
|---|---|---|
| `Devices` | `DeviceID` Text(16), `UserLabelCurrent` Text(20), `UserLabelAuthority` Text(20), `ModelName`, `ParentID`, `ParentGatewayID`, `Port`, `DeviceState`, `BacnetEnabled` | Two-column sync model (see below) |
| `Zones` | `ZoneID` Long, `ZoneName` Text(50), `ZoneNameCurrent` Text(50), `ParentDeviceID`, `Port` | Same two-column pattern |
| `ZoneDevices` | `ZoneID`, `DeviceID` | Zone membership |
| `Users` | — | Contains **hashed passwords**. Never surface or share this table; keep backups off shared/public storage. |

### The two-column sync model
SensorView tracks each label twice: what the device currently reports
(`UserLabelCurrent` / `ZoneNameCurrent`) and what the server believes it should
be (`UserLabelAuthority` / `ZoneName`). When they differ, the UI shows the
item as out-of-sync. **Write both columns to the same value** so the labels
import as "already synced" and push cleanly. (Backups in the wild often carry
pre-existing mismatches — e.g. a blank Authority with a populated Current;
importing a backup surfaces those. Writing both sides fixes them.)

## 2. The pipeline

```
original.svdb ──7z extract──► sensor.mdb ──ODBC UPDATE──► sensor.mdb ──7z pack──► original_relabeled.svdb
      │                                                                                 │
      └──────────────────────── never modified ─────────────────────────────────────────┘
```

1. **Extract** with any 7-zip library (we use Python's `py7zr`). Record the
   archive's member list. (Given a bare `sensor.mdb` instead of an archive, skip
   extract/repack and work on a copy of the database — the tools accept both.)
2. **Edit** `sensor.mdb` through the Microsoft Access ODBC driver
   (`Microsoft Access Driver (*.mdb, *.accdb)` — install the 64-bit
   [Access Database Engine](https://www.microsoft.com/en-us/download/details.aspx?id=54920)
   if missing). Plain SQL:
   ```sql
   UPDATE Devices SET UserLabelCurrent = ?, UserLabelAuthority = ? WHERE DeviceID = ?;
   UPDATE Zones   SET ZoneName = ?, ZoneNameCurrent = ?          WHERE ZoneID   = ?;
   ```
   `ZoneID` is a Long Integer — bind it as a number, not text.
3. **Repackage** with the same 7-zip compression (LZMA2 default) — but write back
   **only the archive's original members**. The ODBC session leaves a `sensor.ldb`
   lock file next to the extracted database; if you sweep the whole temp folder
   into the new archive it will carry that stray file. Rebuild from the recorded
   member list instead.
4. **Never touch the original.** Output to a new `*_relabeled.svdb`.

## 3. Naming rules (what validation enforces, and why)

Labels flow into **BACnet object names** on nLight ECLYPSE (nECY) controllers.
Two independent sets of limits apply — see `LABELING.md` for the full writeup.

**Character rules, from BACnet:** letters/digits plus `_` or `-`, starting with a
letter. No spaces, symbols (`%&#$@?`), slashes, math operators, or non-ASCII. (`$`
is a common habit from electrical drawings; it must go.) Hyphens are legal BACnet
but Acuity documents the underscore as the nLight separator, so the tool accepts a
hyphen and emits an advisory.

**Length, from the SensorView schema — not from BACnet:**

| Column | Type |
|---|---|
| `Devices.UserLabelCurrent`, `UserLabelAuthority` | `VARCHAR(20)` |
| `Zones.ZoneName`, `ZoneNameCurrent` | `VARCHAR(50)` |
| `Devices.UserComments`, `Zones.UserComments` | `VARCHAR(200)` |

BACnet allows 255. SensorView's columns are the binding constraint, and **Access
truncates an over-length write silently** — 30 chars in, 20 stored, no error. That
is why length is validated up front rather than left to the database. Truncation
also forges duplicates out of labels that differed only past the cutoff.

Labels must also be **unique** or points collide. Notes (`UserComments`) are free
text: length-checked only, no character or uniqueness rules.

A convention that worked well in practice (recommended, never enforced):
```
Zone:    {BLDG}_{FLR}_{AREA}          e.g. B1_03_101
Device:  {BLDG}_{FLR}_{ROOM}_{TYPE}_{SEQ}   e.g. B1_03_101_PP_01
```
with a 2-char zero-padded floor, short device-type codes (PP, OS, WS, KP, BRG,
GWY, ECY, …), and a 2-digit sequence per room+type ordered by port then DeviceID.

**Parsing pitfall worth knowing:** if you derive floor/room from existing labels,
beware bare room numbers with no floor prefix (e.g. `816_PP`). A greedy
`\d{1,2}` floor pattern will read "floor 81" out of room 816. Trust the
device's parent bridge/gateway topology for the floor, and sanity-check that
every derived floor is one your site actually has.

## 4. Importing the relabeled backup

In SensorView (v14.x):

1. **Admin → Databases → Import** the `_relabeled.svdb`.
2. If labels show but don't push to devices: **Network Management → Synchronize**.
3. Do **NOT** use **Clear** — it wipes server-side labels and refills them from the
   devices, undoing the import.
4. Verify BACnet object names on the ECLYPSE/BMS side after sync. (The
   `BacnetEnabled` flag in the Devices table may be false across the board even
   when BACnet is served by the nECY — enablement lives at the controller level,
   so check the controller, not the backup.)

### Recommended rollout
- **Dry-run** first (the tools report match counts without writing).
- Test on **one bridge's devices**, import, confirm labels appear + push + BACnet
  names update.
- Then run the full batch. Keep the original backup as rollback.

## 5. What the tools automate

The web tool (`server.py`) and CLI (`cli.py`) wrap the pipeline above with
validation (rules in §3), a CSV rename-list workflow, and safe repackaging.
The rename list itself can be produced however you like — by hand for small
jobs, or generated (e.g. with an AI assistant working from the extracted label
inventory) for thousands of devices. Machine-generated names should get a human
review pass before import.
