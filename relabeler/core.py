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

import os
import re
import shutil
import tempfile
from pathlib import Path

import py7zr
import pyodbc

# Acuity BMS naming rules — these break BACnet point names if violated.
MAX_LABEL = 20
LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*$")
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
    """Read devices and zones with their current labels."""
    cur = _connect(mdb_path).cursor()
    cur.execute("SELECT DeviceID, UserLabelCurrent FROM Devices")
    devices = [
        {"id": str(d).strip(), "current": (c or "").strip()}
        for d, c in cur.fetchall()
    ]
    cur.execute("SELECT ZoneID, ZoneName, ZoneNameCurrent FROM Zones")
    zones = [
        {"id": str(z).strip(), "current": ((n or c) or "").strip()}
        for z, n, c in cur.fetchall()
    ]
    devices.sort(key=lambda r: r["current"] or r["id"])
    zones.sort(key=lambda r: r["current"] or r["id"])
    return {"devices": devices, "zones": zones}


def validate(dev_map: dict, zone_map: dict) -> list[str]:
    """Return a list of human-readable problems; empty list means clean."""
    problems = []

    def scan(mapping, kind):
        labels = [v.strip() for v in mapping.values() if v and v.strip()]
        for lbl in labels:
            if not LABEL_RE.fullmatch(lbl):
                problems.append(f"{kind}: '{lbl}' — must start with a letter and use only letters/digits/underscores")
            if len(lbl) > MAX_LABEL:
                problems.append(f"{kind}: '{lbl}' — {len(lbl)} chars, over the {MAX_LABEL} limit")
            parts = lbl.split("_")
            if len(parts) > 1 and parts[1] not in VALID_FLOORS and "Site" not in lbl:
                problems.append(f"{kind}: '{lbl}' — floor token '{parts[1]}' not in 01-12/P1/PH")
        seen, dups = set(), set()
        for lbl in labels:
            (dups if lbl in seen else seen).add(lbl)
        for d in sorted(dups):
            problems.append(f"{kind}: '{d}' — duplicate label (must be unique)")

    scan(dev_map, "device")
    scan(zone_map, "zone")
    return problems


def apply_labels(mdb_path: str, dev_map: dict, zone_map: dict) -> tuple[int, int]:
    """Write new labels into the mdb. Blank/absent values are left unchanged.
    Returns (devices_changed, zones_changed)."""
    conn = _connect(mdb_path)
    cur = conn.cursor()
    dcount = zcount = 0
    for did, label in dev_map.items():
        label = (label or "").strip()
        if not label:
            continue
        cur.execute(
            "UPDATE Devices SET UserLabelCurrent = ?, UserLabelAuthority = ? WHERE DeviceID = ?",
            (label, label, str(did).strip()),
        )
        dcount += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 1
    for zid, name in zone_map.items():
        name = (name or "").strip()
        if not name:
            continue
        cur.execute(
            "UPDATE Zones SET ZoneName = ?, ZoneNameCurrent = ? WHERE ZoneID = ?",
            (name, name, int(str(zid).strip())),
        )
        zcount += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 1
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


def relabel(in_path: str, dev_map: dict, zone_map: dict, out_path: str) -> dict:
    """Full pipeline against freshly staged input (archive or bare .mdb).
    Output mirrors the input: archive in -> rebuilt archive out; bare .mdb in ->
    edited .mdb copy out. Returns a summary dict."""
    problems = validate(dev_map, zone_map)
    if problems:
        raise ValueError("Validation failed:\n" + "\n".join(problems))
    tmp = tempfile.mkdtemp(prefix="svrelabel_")
    mdb, members = prepare_input(in_path, tmp)
    dchg, zchg = apply_labels(mdb, dev_map, zone_map)
    if members is None:
        shutil.copy2(mdb, out_path)  # bare database: the edited copy IS the output
    else:
        repackage_svdb(tmp, members, out_path)
    return {"devices_changed": dchg, "zones_changed": zchg, "output": out_path}
