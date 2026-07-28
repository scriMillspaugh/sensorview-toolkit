"""
Core relabel engine for the SensorView backup relabeler web tool.

Mirrors the tested logic in ../updater/update_labels.py:
  - a .svdb is a 7-zip archive containing sensor.mdb (MS Access JET4)
  - devices carry UserLabelCurrent + UserLabelAuthority (both written together)
  - zones carry ZoneName + ZoneNameCurrent (both written together)
  - the original file is never modified; output is always a new _relabeled copy
  - repackage writes back only the archive's ORIGINAL members (never the Access
    .ldb lock file that ODBC leaves in the temp dir)

This module has no web dependencies so it can be unit-tested and packaged.
"""
from __future__ import annotations

__version__ = "1.1.0"

import os
import re
import shutil
import tempfile
from pathlib import Path

import py7zr
import pyodbc

LABELING_DOCS = "https://github.com/scriMillspaugh/sensorview-toolkit/blob/main/LABELING.md"

# Hard limits, measured from the sensor.mdb schema (not from BACnet, which is far
# looser — 255 max, ~50 in practice). Access SILENTLY TRUNCATES an over-length
# write: 30 chars in, 20 stored, no error raised. So these must be checked before
# the UPDATE, or labels get mangled — and truncation can forge duplicates out of
# labels that differed only past the cutoff.
#   Devices.UserLabelCurrent / UserLabelAuthority  VARCHAR(20)
#   Zones.ZoneName / ZoneNameCurrent               VARCHAR(50)
MAX_DEVICE_LABEL = 20
MAX_ZONE_LABEL = 50
MAX_LABEL_BY_KIND = {"device": MAX_DEVICE_LABEL, "zone": MAX_ZONE_LABEL}

# Devices.UserComments / Zones.UserComments  VARCHAR(200). Free text — the BACnet
# character rules do not apply, but the same silent truncation does.
MAX_COMMENT = 200

# One regex covers every BACnet character restriction: ASCII letters/digits plus
# the two accepted delimiters, and a mandatory letter first. It rejects spaces,
# %&#$@?, slashes, math operators, and non-ASCII glyphs by construction.
LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")

# Advisory only — never blocking. See advisories() and LABELING.md.
VALID_FLOORS = {f"{n:02d}" for n in range(1, 13)} | {"P1", "PH"}


def find_access_driver() -> str:
    """Return an installed MS Access ODBC driver name, preferring the modern one."""
    drivers = [d for d in pyodbc.drivers() if "Access" in d or "*.mdb" in d]
    if not drivers:
        raise RuntimeError(
            "No Microsoft Access ODBC driver found. Install the Microsoft Access "
            "Database Engine: https://www.microsoft.com/en-us/download/details.aspx?id=54920"
        )
    # Prefer the .accdb-capable driver if present.
    for d in drivers:
        if "accdb" in d:
            return d
    return drivers[0]


def _connect(mdb_path: str) -> pyodbc.Connection:
    return pyodbc.connect(f"DRIVER={{{find_access_driver()}}};DBQ={mdb_path};")


def extract_svdb(svdb_path: str, dest_dir: str) -> tuple[str, list[str]]:
    """Extract the archive. Returns (sensor.mdb path, original member names)."""
    with py7zr.SevenZipFile(svdb_path, mode="r") as z:
        members = list(z.getnames())
        z.extractall(path=dest_dir)
    mdb = os.path.join(dest_dir, "sensor.mdb")
    if not os.path.exists(mdb):
        raise RuntimeError("sensor.mdb not found inside the .svdb — is this a SensorView backup?")
    return mdb, members


def prepare_input(in_path: str, dest_dir: str) -> tuple[str, list[str] | None]:
    """Stage an input file for editing. Accepts either a .svdb/.svdo archive or a
    bare Access database (.mdb). Returns (editable mdb path, archive member list).
    Members is None for a bare .mdb — meaning output should also be a bare .mdb.

    A bare .mdb is COPIED into dest_dir first so the original file is never
    touched (the ODBC edits happen on the copy)."""
    if in_path.lower().endswith(".mdb"):
        staged = os.path.join(dest_dir, os.path.basename(in_path))
        if os.path.abspath(staged) != os.path.abspath(in_path):
            shutil.copy2(in_path, staged)  # already inside dest_dir (e.g. an upload) needs no copy
        return staged, None
    return extract_svdb(in_path, dest_dir)


def read_tables(mdb_path: str) -> dict:
    """Read devices and zones with their current labels and notes."""
    cur = _connect(mdb_path).cursor()
    cur.execute("SELECT DeviceID, UserLabelCurrent, UserComments FROM Devices")
    devices = [
        {"id": str(d).strip(), "current": (c or "").strip(), "notes": (m or "").strip()}
        for d, c, m in cur.fetchall()
    ]
    cur.execute("SELECT ZoneID, ZoneName, ZoneNameCurrent, UserComments FROM Zones")
    zones = [
        {"id": str(z).strip(), "current": ((n or c) or "").strip(), "notes": (m or "").strip()}
        for z, n, c, m in cur.fetchall()
    ]
    devices.sort(key=lambda r: r["current"] or r["id"])
    zones.sort(key=lambda r: r["current"] or r["id"])
    return {"devices": devices, "zones": zones}


def validate(dev_map: dict, zone_map: dict,
             dev_notes: dict | None = None, zone_notes: dict | None = None) -> list[str]:
    """Return a list of human-readable problems; empty list means clean.

    These are the BACnet character rules and the SensorView column limits only —
    breaking one produces a label the BMS cannot use or that Access truncates on
    write. relabel() refuses to write while any of these stand. Naming *structure*
    is not checked here; see advisories() and LABELING.md.

    Notes (UserComments) are free text and are length-checked only — they are not
    BACnet object names, so the character and uniqueness rules do not apply."""
    problems = []

    def scan(mapping, kind):
        limit = MAX_LABEL_BY_KIND[kind]
        labels = [v.strip() for v in mapping.values() if v and v.strip()]
        for lbl in labels:
            if not LABEL_RE.fullmatch(lbl):
                problems.append(
                    f"{kind}: '{lbl}' — must start with a letter and use only "
                    f"letters, digits, underscores, or hyphens (no spaces, symbols, or accents)"
                )
            if len(lbl) > limit:
                problems.append(
                    f"{kind}: '{lbl}' — {len(lbl)} chars, over the {limit}-char "
                    f"SensorView limit for {kind}s (Access truncates silently)"
                )
        seen, dups = set(), set()
        for lbl in labels:
            (dups if lbl in seen else seen).add(lbl)
        for d in sorted(dups):
            problems.append(f"{kind}: '{d}' — duplicate label (must be unique)")

    def scan_notes(mapping, kind):
        for note in {(v or "").strip() for v in (mapping or {}).values() if (v or "").strip()}:
            if len(note) > MAX_COMMENT:
                problems.append(
                    f"{kind} note: {len(note)} chars, over the {MAX_COMMENT}-char "
                    f"limit (Access truncates silently) — starts '{note[:40]}…'"
                )

    scan(dev_map, "device")
    scan(zone_map, "zone")
    scan_notes(dev_notes, "device")
    scan_notes(zone_notes, "zone")
    return problems


def advisories(dev_map: dict, zone_map: dict) -> list[str]:
    """Return non-blocking notes; empty list means nothing to flag.

    These check the recommended practice documented in LABELING.md, not anything
    the BMS requires. Every site names differently, so an advisory NEVER blocks a
    write — use your own convention and ignore these freely."""
    notes = []

    def scan(mapping, kind):
        seen = set()
        for v in mapping.values():
            lbl = (v or "").strip()
            if not lbl or lbl in seen:  # one note per distinct label, not per row
                continue
            seen.add(lbl)
            # BACnet permits hyphens; Acuity documentation calls for underscores.
            # Allowed either way, flagged so the ambiguity stays visible.
            if "-" in lbl:
                notes.append(
                    f"{kind}: '{lbl}' — uses a hyphen. Valid BACnet, but Acuity "
                    f"documents the underscore as the nLight separator; underscores "
                    f"are the safer choice."
                )
            # Catches the room-number mis-parse in METHOD.md: a bare '816_PP'
            # reading as floor 81. Only meaningful under the recommended format.
            parts = lbl.split("_")
            if len(parts) > 1 and parts[1] not in VALID_FLOORS and "Site" not in lbl:
                notes.append(
                    f"{kind}: '{lbl}' — 2nd field '{parts[1]}' is not a floor token "
                    f"(01-12/P1/PH). Expected if you use your own scheme — just check "
                    f"it isn't a mis-parsed room number."
                )

    scan(dev_map, "device")
    scan(zone_map, "zone")
    if notes:
        notes.append(f"Recommended naming practice: {LABELING_DOCS}")
    return notes


def apply_labels(mdb_path: str, dev_map: dict, zone_map: dict,
                 dev_notes: dict | None = None, zone_notes: dict | None = None) -> tuple[int, int]:
    """Write new labels and notes into the mdb. Blank/absent values are left
    unchanged — a blank note clears nothing, it just skips the column.
    Returns (devices_changed, zones_changed); a row counts once even if both its
    label and its note were written."""
    dev_notes = dev_notes or {}
    zone_notes = zone_notes or {}
    conn = _connect(mdb_path)
    cur = conn.cursor()

    def rows_hit():
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 1

    dcount = 0
    for did in dev_map.keys() | dev_notes.keys():
        label = (dev_map.get(did) or "").strip()
        note = (dev_notes.get(did) or "").strip()
        if not label and not note:
            continue
        key = str(did).strip()
        touched = 0
        if label:
            cur.execute(
                "UPDATE Devices SET UserLabelCurrent = ?, UserLabelAuthority = ? WHERE DeviceID = ?",
                (label, label, key),
            )
            touched = rows_hit()
        if note:
            cur.execute("UPDATE Devices SET UserComments = ? WHERE DeviceID = ?", (note, key))
            touched = max(touched, rows_hit())
        dcount += touched

    zcount = 0
    for zid in zone_map.keys() | zone_notes.keys():
        name = (zone_map.get(zid) or "").strip()
        note = (zone_notes.get(zid) or "").strip()
        if not name and not note:
            continue
        key = int(str(zid).strip())
        touched = 0
        if name:
            cur.execute(
                "UPDATE Zones SET ZoneName = ?, ZoneNameCurrent = ? WHERE ZoneID = ?",
                (name, name, key),
            )
            touched = rows_hit()
        if note:
            cur.execute("UPDATE Zones SET UserComments = ? WHERE ZoneID = ?", (note, key))
            touched = max(touched, rows_hit())
        zcount += touched

    conn.commit()
    conn.close()
    return dcount, zcount


def repackage_svdb(src_dir: str, members: list[str], output_svdb: str) -> None:
    """Repackage into a .svdb (7-zip, LZMA2 — matches SensorView). Writes back
    exactly the archive's original members, never the Access .ldb lock file."""
    src = Path(src_dir)
    with py7zr.SevenZipFile(output_svdb, mode="w") as z:
        for name in members:
            p = src / name
            if p.is_file():
                z.write(str(p), name)


def relabel(in_path: str, dev_map: dict, zone_map: dict, out_path: str,
            dev_notes: dict | None = None, zone_notes: dict | None = None) -> dict:
    """Full pipeline against freshly staged input (archive or bare .mdb).
    Output mirrors the input: archive in -> rebuilt archive out; bare .mdb in ->
    edited .mdb copy out. Returns a summary dict."""
    problems = validate(dev_map, zone_map, dev_notes, zone_notes)
    if problems:
        raise ValueError("Validation failed:\n" + "\n".join(problems))
    tmp = tempfile.mkdtemp(prefix="svrelabel_")
    mdb, members = prepare_input(in_path, tmp)
    dchg, zchg = apply_labels(mdb, dev_map, zone_map, dev_notes, zone_notes)
    if members is None:
        shutil.copy2(mdb, out_path)  # bare database: the edited copy IS the output
    else:
        repackage_svdb(tmp, members, out_path)
    return {"devices_changed": dchg, "zones_changed": zchg, "output": out_path}
