"""
Core relabel engine for the SensorView Label Editor web tool.

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

__version__ = "1.3.0"

import os
import re
import shutil
import tempfile
from pathlib import Path

import py7zr
import pyodbc

LABELING_DOCS = "https://github.com/scriMillspaugh/sensorview-toolkit/blob/main/label-editor/docs/LABELING.md"

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

# One regex covers every character restriction: ASCII letters/digits plus the
# underscore, and a mandatory letter first. It rejects spaces, %&#$@?, slashes,
# math operators, and non-ASCII glyphs by construction. BACnet itself would accept
# a hyphen, but Acuity's nLight BMS integration rules allow the underscore only,
# so the hyphen is refused too (1.3.0; it was an advisory in 1.1.0-1.2.0).
LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")

# What Excel does to an ID column it decides is a number. Both are caught before
# any write, because an UPDATE against a mangled ID matches nothing and fails
# silently. See LABELING.md, "Editing the CSV in Excel".
#   - a hex ID such as 381E0024 is read as 381 x 10^24 and saved as "3.81E+26";
#     the digits are gone and cannot be recovered from the CSV.
#   - an all-digit ID such as 02319041 loses its leading zero -> "2319041".
EXCEL_SCI_RE = re.compile(r"\d+(\.\d+)?E\+\d+", re.IGNORECASE)

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
                if "-" in lbl and LABEL_RE.fullmatch(lbl.replace("-", "_")):
                    problems.append(
                        f"{kind}: '{lbl}' — hyphens are not allowed in nLight labels; "
                        f"use an underscore ('{lbl.replace('-', '_')}')"
                    )
                else:
                    problems.append(
                        f"{kind}: '{lbl}' — must start with a letter and use only "
                        f"letters, digits, and underscores (no hyphens, spaces, symbols, or accents)"
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


def check_ids(tables: dict, dev_map: dict, zone_map: dict,
              dev_notes: dict | None = None, zone_notes: dict | None = None) -> tuple[list[str], list[str]]:
    """Match the rename list's IDs against the backup. Returns (problems, unmatched).

    problems — IDs that look like Excel damaged them (see EXCEL_SCI_RE). These
    block the write: the list is untrustworthy as a whole, and a sci-notation ID
    cannot be repaired. Re-export the template, or re-open the CSV with the ID
    column set to Text.
    unmatched — IDs that are simply not in this backup (a device removed since the
    list was made, or a list from another site). Reported, not written."""
    problems, unmatched = [], []
    for kind, rows, ids in (("device", tables["devices"], set((dev_map or {}).keys()) | set((dev_notes or {}).keys())),
                            ("zone", tables["zones"], set((zone_map or {}).keys()) | set((zone_notes or {}).keys()))):
        known = {r["id"] for r in rows}
        by_stripped = {}
        for k in known:
            by_stripped.setdefault(k.lstrip("0") or "0", []).append(k)
        for rid in sorted(ids):
            rid = str(rid).strip()
            if rid in known:
                continue
            if EXCEL_SCI_RE.fullmatch(rid):
                problems.append(
                    f"{kind} ID '{rid}' — Excel turned this ID into a number in scientific "
                    f"notation; the original digits are lost. Re-download the template, or "
                    f"open the CSV with the ID column set to Text."
                )
            elif rid.isdigit() and any(k != rid for k in by_stripped.get(rid, [])):
                full = next(k for k in by_stripped[rid] if k != rid)
                problems.append(
                    f"{kind} ID '{rid}' — looks like '{full}' with its leading zeros "
                    f"removed by Excel. Open the CSV with the ID column set to Text."
                )
            else:
                unmatched.append(f"{kind} ID '{rid}' — not in this backup; skipped")
    return problems, unmatched


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
        # -1 means the driver did not report a count; 0 means the ID matched
        # nothing and must not be reported as a change.
        return cur.rowcount if cur.rowcount >= 0 else 1

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
    tables = read_tables(mdb)
    id_problems, unmatched = check_ids(tables, dev_map, zone_map, dev_notes, zone_notes)
    if id_problems:
        raise ValueError("Rename list IDs look damaged:\n" + "\n".join(id_problems))
    # Write only IDs the backup actually has; the rest are reported in "unmatched".
    dev_ids = {r["id"] for r in tables["devices"]}
    zone_ids = {r["id"] for r in tables["zones"]}
    dev_map = {k: v for k, v in dev_map.items() if str(k).strip() in dev_ids}
    zone_map = {k: v for k, v in zone_map.items() if str(k).strip() in zone_ids}
    dev_notes = {k: v for k, v in (dev_notes or {}).items() if str(k).strip() in dev_ids}
    zone_notes = {k: v for k, v in (zone_notes or {}).items() if str(k).strip() in zone_ids}
    dchg, zchg = apply_labels(mdb, dev_map, zone_map, dev_notes, zone_notes)
    if members is None:
        shutil.copy2(mdb, out_path)  # bare database: the edited copy IS the output
    else:
        repackage_svdb(tmp, members, out_path)
    return {"devices_changed": dchg, "zones_changed": zchg, "output": out_path,
            "unmatched": unmatched}
