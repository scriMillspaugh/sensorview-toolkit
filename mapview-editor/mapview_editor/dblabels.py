"""Read-only label loader for SensorView databases (.svdb / bare .mdb).

Deliberately duplicates a small slice of label-editor/core.py: the two tools
ship as independent one-file exes with no shared package. Read-only by
construction — ReadOnly=1 connection, closed before returning, nothing written.

pyodbc and the Access ODBC driver are optional: both are checked lazily and
their absence raises LabelsUnavailable so the server can degrade gracefully
(database labels off, map editing unaffected).
"""

import contextlib
import os

import py7zr


class LabelsUnavailable(RuntimeError):
    """pyodbc or the Access ODBC driver is missing — feature off, tool fine."""


def _pyodbc():
    try:
        import pyodbc
    except ImportError:
        raise LabelsUnavailable(
            "pyodbc is not installed — database labels are disabled. "
            "Map editing is unaffected. Install with: py -m pip install pyodbc"
        )
    return pyodbc


def find_access_driver(pyodbc):
    drivers = [d for d in pyodbc.drivers() if "Access" in d or "*.mdb" in d]
    if not drivers:
        raise LabelsUnavailable(
            "No Microsoft Access ODBC driver found — database labels are disabled. "
            "Map editing is unaffected. Install the Access Database Engine: "
            "https://www.microsoft.com/en-us/download/details.aspx?id=54920"
        )
    for d in drivers:
        if "accdb" in d:
            return d
    return drivers[0]


def stage_mdb(in_path: str, dest_dir: str) -> str:
    """Return a readable .mdb path. Archives are extracted into dest_dir;
    a bare .mdb (already an upload copy inside dest_dir) is used in place."""
    if in_path.lower().endswith(".mdb"):
        return in_path
    with py7zr.SevenZipFile(in_path, mode="r") as z:
        names = z.getnames()
        z.extractall(path=dest_dir)
    mdbs = [n for n in names if n.lower().endswith(".mdb")]
    if not mdbs:
        raise RuntimeError(
            "No .mdb found inside the archive — is this a SensorView backup (.svdb)?"
        )
    preferred = next(
        (n for n in mdbs if os.path.basename(n).lower() == "sensor.mdb"), mdbs[0]
    )
    return os.path.join(dest_dir, preferred)


def read_labels(mdb_path: str) -> dict:
    """Read device and zone labels, keyed for joining to .mvdb map data.

    Returns {"devices": {DEVICEID: label}, "models": {DEVICEID: model},
    "zones": {zoneId: label}, "zonesByParent": {"DEVICEID:port": label}} —
    keys upper-cased/stripped so lookups match the map's normalized IDs.
    Rows with no label are omitted from "devices" (but keep their model).
    """
    pyodbc = _pyodbc()
    driver = find_access_driver(pyodbc)
    conn = pyodbc.connect(f"DRIVER={{{driver}}};DBQ={mdb_path};ReadOnly=1;")
    with contextlib.closing(conn):
        cur = conn.cursor()
        try:
            cur.execute("SELECT DeviceID, UserLabelCurrent, ModelName FROM Devices")
            rows = cur.fetchall()
        except pyodbc.Error:
            # Older schema without ModelName — labels still work, colors don't.
            cur.execute("SELECT DeviceID, UserLabelCurrent FROM Devices")
            rows = [(d, lbl, None) for d, lbl in cur.fetchall()]
        devices, models = {}, {}
        for d, lbl, model in rows:
            key = str(d).strip().upper()
            if (lbl or "").strip():
                devices[key] = str(lbl).strip()
            if (model or "").strip():
                models[key] = str(model).strip()
        cur.execute(
            "SELECT ZoneID, ZoneName, ZoneNameCurrent, ParentDeviceID, Port FROM Zones"
        )
        zones, zones_by_parent = {}, {}
        for zid, name, current, parent, port in cur.fetchall():
            label = ((name or current) or "").strip()  # same preference as label-editor
            if not label:
                continue
            zones[str(zid).strip()] = label
            if parent is not None and port is not None:
                zones_by_parent[f"{str(parent).strip().upper()}:{int(port)}"] = label
    return {"devices": devices, "models": models,
            "zones": zones, "zonesByParent": zones_by_parent}
