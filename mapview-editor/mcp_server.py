"""MCP server for the MapView Editor — lets an AI assistant (Claude) build and
edit floorplan drawings through the running editor, live.

It talks HTTP to the local editor server (http://127.0.0.1:5111), which stays
the single source of truth. The browser UI polls a revision counter and
reloads on external changes, so edits made through these tools appear in the
open editor within a couple of seconds.

Coordinates: every tool speaks IMAGE coordinates — x right, y DOWN from the
top-left, matching the floorplan PNG and device markers. Zone polygons are
stored y-up in the archive; this server converts on read and write so callers
never deal with the flip.

Usage:
  1. Start the editor:  py server.py   (and load a .mvdb, or use load_mvdb)
  2. Register with Claude Code:  claude mcp add mapview -- py mcp_server.py

Requires:  py -m pip install mcp
"""

import json
import os
import re
import urllib.error
import urllib.request
import uuid

from mcp.server.fastmcp import FastMCP

BASE = "http://127.0.0.1:5111"

mcp = FastMCP(
    "mapview-editor",
    instructions=(
        "Tools for editing Acuity nLight MapView floorplans through the local "
        "MapView Editor. All coordinates are image-space: x right, y down from "
        "the top-left, in pixels of the floorplan PNG. Call get_status first; "
        "if no maps are loaded, ask the user to load a .mvdb (or call "
        "load_mvdb with a file path)."
    ),
)


def _request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("error", str(e))
        except Exception:
            detail = str(e)
        raise RuntimeError(f"Editor API error ({e.code}): {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"MapView Editor is not reachable at {BASE}. "
            f"Start it first: py server.py  ({e.reason})"
        )


def _post_file(path: str, filepath: str) -> dict:
    """Multipart upload without extra dependencies."""
    if not os.path.isfile(filepath):
        raise RuntimeError(f"File not found: {filepath}")
    boundary = uuid.uuid4().hex
    fname = os.path.basename(filepath)
    with open(filepath, "rb") as fh:
        content = fh.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("error", str(e))
        except Exception:
            detail = str(e)
        raise RuntimeError(f"Editor API error ({e.code}): {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"MapView Editor is not reachable at {BASE}. "
            f"Start it first: py server.py  ({e.reason})"
        )


def _get_map_data(file_key: str) -> dict:
    return _request("GET", f"/api/map/{file_key}/data")


def _put_map_data(file_key: str, data: dict) -> dict:
    return _request("PUT", f"/api/map/{file_key}/data", data)


# Zone WKT AND device y are stored y-up (origin bottom-left); the floorplan
# PNG is y-down. Flip on read AND write so tool callers only ever see image
# coordinates. (Device y was misread as y-down until v1.2.0.)

def _wkt_to_points(wkt: str, height: float) -> list[list[float]]:
    m = re.search(r"POLYGON\(\((.*)\)\)", wkt or "", re.IGNORECASE)
    if not m:
        return []
    pts = []
    for pair in m.group(1).split(","):
        xy = pair.strip().split()
        if len(xy) == 2:
            pts.append([float(xy[0]), height - float(xy[1])])
    return pts


def _points_to_wkt(points: list, height: float) -> str:
    coords = ",".join(f"{float(x)} {height - float(y)}" for x, y in points)
    return f"POLYGON(({coords}))"


def _labels() -> dict:
    data = _request("GET", "/api/labels")
    return data if data.get("loaded") else {}


@mcp.tool()
def get_status() -> dict:
    """Editor status: version, loaded maps, whether database labels are loaded.
    Call this first to see what's available."""
    version = _request("GET", "/api/version").get("version")
    mapinfo = _request("GET", "/api/mapinfo")
    labels = _request("GET", "/api/labels")
    return {
        "editorVersion": version,
        "mapsLoaded": len(mapinfo.get("maps", [])),
        "labelsLoaded": bool(labels.get("loaded")),
        "labelsSource": labels.get("source"),
        "note": "No maps loaded — load a .mvdb in the browser or call load_mvdb."
                if not mapinfo.get("maps") else "Ready.",
    }


@mcp.tool()
def load_mvdb(path: str) -> dict:
    """Load a .mvdb MapView export into the editor from a local file path.
    Replaces whatever is currently loaded."""
    data = _post_file("/api/upload", path)
    return {"ok": True, "mapsLoaded": len(data.get("mapinfo", {}).get("maps", []))}


@mcp.tool()
def load_database(path: str) -> dict:
    """Load a SensorView database (.svdb or sensor.mdb) read-only, so devices
    get plain-language names and models. The database file is never modified."""
    data = _post_file("/api/labels", path)
    return {"ok": True, "source": data.get("source"), "stats": data.get("stats")}


@mcp.tool()
def list_maps() -> list[dict]:
    """All maps in the loaded .mvdb: file key, building group, floor name,
    plus device and zone counts."""
    mapinfo = _request("GET", "/api/mapinfo")
    out = []
    for entry in mapinfo.get("maps", []):
        data = _get_map_data(entry["file"])
        out.append({
            "file": entry["file"],
            "group": entry.get("group", ""),
            "name": entry.get("name", ""),
            "devices": len(data.get("devices", [])),
            "zones": len(data.get("zones", [])),
            "width": data.get("width"),
            "height": data.get("height"),
        })
    return out


@mcp.tool()
def get_map(file_key: str) -> dict:
    """Full contents of one map: dimensions, devices (id, x, y, plus name and
    model when a database is loaded), and zones with polygon points in image
    coordinates (y down)."""
    data = _get_map_data(file_key)
    height = data.get("height", 3000)
    labels = _labels()
    dev_names = labels.get("devices", {})
    dev_models = labels.get("models", {})
    devices = []
    for d in data.get("devices", []):
        key = str(d.get("id", "")).strip().upper()
        devices.append({
            "id": d.get("id"), "x": d.get("x"),
            "y": round(height - float(d.get("y", 0)), 1),
            "name": dev_names.get(key), "model": dev_models.get(key),
        })
    zones = []
    for z in data.get("zones", []):
        zones.append({
            "id": z.get("id"),
            "parentDeviceId": z.get("ParentDeviceID", ""),
            "port": z.get("Port", 0),
            "points": _wkt_to_points(z.get("coords", ""), height),
        })
    return {"file": file_key, "width": data.get("width"),
            "height": height, "devices": devices, "zones": zones}


@mcp.tool()
def create_map(group: str, name: str) -> dict:
    """Create a new empty map (e.g. group='BUILDING A', name='LEVEL 05').
    A floorplan PNG can be attached later in the browser."""
    data = _request("POST", "/api/map/create", {"group": group, "name": name})
    return {"ok": True, "file": data.get("file")}


@mcp.tool()
def add_devices(file_key: str, devices: list[dict]) -> dict:
    """Add device markers to a map. Each item: {"id": "<hex device id>",
    "x": <px>, "y": <px>} in IMAGE coordinates — y measured DOWN from the top.
    WARNING: coordinates taken from CAD drawings, PDFs, or WKT are usually
    y-UP (measured from the bottom); convert those first with
    y_image = map_height - y_source, or the markers will appear mirrored
    (flip_devices_y repairs that). Placing a marker does NOT create a device
    in SensorView — it positions an existing one. Returns a warning list for
    IDs already on this map (allowed, but usually a mistake)."""
    data = _get_map_data(file_key)
    height = data.get("height", 3000)
    existing = {str(d.get("id", "")).strip().upper() for d in data.get("devices", [])}
    warnings = []
    data.setdefault("devices", [])
    for d in devices:
        did = str(d["id"]).strip().upper()
        if did in existing:
            warnings.append(f"{did} was already on this map — added a second marker")
        existing.add(did)
        data["devices"].append({"id": did, "x": round(float(d["x"]), 1),
                                "y": round(height - float(d["y"]), 1)})
    _put_map_data(file_key, data)
    return {"ok": True, "added": len(devices),
            "totalOnMap": len(data["devices"]), "warnings": warnings}


@mcp.tool()
def move_device(file_key: str, device_id: str, x: float, y: float,
                occurrence: int = 0) -> dict:
    """Move a device marker to new image coordinates. If the same ID appears
    more than once on the map, `occurrence` picks which one (0-based)."""
    data = _get_map_data(file_key)
    matches = [d for d in data.get("devices", [])
               if str(d.get("id", "")).strip().upper() == device_id.strip().upper()]
    if not matches:
        raise RuntimeError(f"Device {device_id} is not on map {file_key}")
    if occurrence >= len(matches):
        raise RuntimeError(f"Device {device_id} appears {len(matches)}x; occurrence {occurrence} does not exist")
    matches[occurrence]["x"] = round(float(x), 1)
    matches[occurrence]["y"] = round(data.get("height", 3000) - float(y), 1)
    _put_map_data(file_key, data)
    return {"ok": True, "occurrences": len(matches)}


@mcp.tool()
def remove_device(file_key: str, device_id: str, occurrence: int = 0) -> dict:
    """Remove a device marker from a map (the marker only, nothing in
    SensorView). If the ID appears more than once, `occurrence` picks which."""
    data = _get_map_data(file_key)
    idxs = [i for i, d in enumerate(data.get("devices", []))
            if str(d.get("id", "")).strip().upper() == device_id.strip().upper()]
    if not idxs:
        raise RuntimeError(f"Device {device_id} is not on map {file_key}")
    if occurrence >= len(idxs):
        raise RuntimeError(f"Device {device_id} appears {len(idxs)}x; occurrence {occurrence} does not exist")
    data["devices"].pop(idxs[occurrence])
    _put_map_data(file_key, data)
    return {"ok": True, "remainingOccurrences": len(idxs) - 1}


@mcp.tool()
def add_zone(file_key: str, points: list, parent_device_id: str = "",
             port: int = 0, zone_id: int | None = None) -> dict:
    """Draw a zone polygon. `points` is a list of [x, y] pairs in image
    coordinates (y down), at least 3; the polygon closes automatically.
    `parent_device_id` is the owning device (typically a bridge) and `port`
    its port. Omit zone_id to auto-pick the next free one."""
    if len(points) < 3:
        raise RuntimeError("A zone needs at least 3 points")
    data = _get_map_data(file_key)
    height = data.get("height", 3000)
    data.setdefault("zones", [])
    used = {z.get("id") for z in data["zones"]}
    if zone_id is None:
        zone_id = 1
        while zone_id in used:
            zone_id += 1
    elif zone_id in used:
        raise RuntimeError(f"Zone id {zone_id} already exists on this map")
    pts = [list(map(float, p)) for p in points]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    data["zones"].append({
        "id": zone_id,
        "ParentDeviceID": parent_device_id.strip().upper(),
        "Port": int(port),
        "coords": _points_to_wkt(pts, height),
    })
    _put_map_data(file_key, data)
    return {"ok": True, "zoneId": zone_id, "totalZones": len(data["zones"])}


@mcp.tool()
def flip_devices_y(file_key: str, device_ids: list[str] | None = None) -> dict:
    """Repair tool: mirror device markers vertically (y -> map_height - y).
    Use when markers were placed from y-up source coordinates (CAD/PDF/WKT)
    and appear flipped against the floorplan. Omit device_ids to flip every
    device on the map; pass a list of IDs to flip only those. Running it
    twice returns markers to where they started."""
    data = _get_map_data(file_key)
    height = data.get("height", 3000)
    wanted = ({i.strip().upper() for i in device_ids} if device_ids else None)
    flipped = 0
    for d in data.get("devices", []):
        if wanted is None or str(d.get("id", "")).strip().upper() in wanted:
            d["y"] = round(height - float(d["y"]), 1)
            flipped += 1
    if not flipped:
        raise RuntimeError("No matching devices to flip on this map")
    _put_map_data(file_key, data)
    return {"ok": True, "flipped": flipped, "mapHeight": height}


@mcp.tool()
def remove_zone(file_key: str, zone_id: int) -> dict:
    """Delete a zone polygon from a map."""
    data = _get_map_data(file_key)
    before = len(data.get("zones", []))
    data["zones"] = [z for z in data.get("zones", []) if z.get("id") != zone_id]
    if len(data["zones"]) == before:
        raise RuntimeError(f"Zone {zone_id} is not on map {file_key}")
    _put_map_data(file_key, data)
    return {"ok": True, "remainingZones": len(data["zones"])}


@mcp.tool()
def search_devices(query: str) -> list[dict]:
    """Find devices across ALL maps by hex ID or (with a database loaded)
    plain-language name. Returns id, name, model, map, and position."""
    q = query.strip().upper()
    index = _request("GET", "/api/index").get("devices", [])
    labels = _labels()
    dev_names = labels.get("devices", {})
    dev_models = labels.get("models", {})
    mapinfo = _request("GET", "/api/mapinfo")
    map_names = {m["file"]: m.get("name", m["file"]) for m in mapinfo.get("maps", [])}
    heights = {}
    out = []
    for d in index:
        key = str(d.get("id", "")).strip().upper()
        name = dev_names.get(key)
        if q in key or (name and q in name.upper()):
            if d["map"] not in heights:
                heights[d["map"]] = _get_map_data(d["map"]).get("height", 3000)
            out.append({"id": d["id"], "name": name, "model": dev_models.get(key),
                        "map": d["map"], "mapName": map_names.get(d["map"]),
                        "x": d["x"], "y": round(heights[d["map"]] - float(d["y"]), 1)})
    return out[:100]


@mcp.tool()
def export_mvdb(dest_path: str) -> dict:
    """Repackage the current state as a new .mvdb and write it to dest_path.
    The originally loaded file is never modified."""
    req = urllib.request.Request(BASE + "/api/export", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            content = r.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"Export failed — is the editor running? ({e})")
    if not dest_path.lower().endswith(".mvdb"):
        dest_path += ".mvdb"
    with open(dest_path, "wb") as fh:
        fh.write(content)
    return {"ok": True, "path": os.path.abspath(dest_path),
            "sizeBytes": len(content)}


if __name__ == "__main__":
    mcp.run()
