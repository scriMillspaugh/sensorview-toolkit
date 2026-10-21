"""MapView Editor — local Flask server for editing .mvdb floorplan archives."""

__version__ = "1.4.0"

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path
from threading import Timer

import py7zr
from flask import Flask, jsonify, request, send_file, send_from_directory


class ExportArchive(py7zr.SevenZipFile):
    """A 7z writer that produces the entry shape SensorView's importer expects.

    SensorView's own MapView export stores every member with Windows attributes
    = 32 (FILE_ATTRIBUTE_ARCHIVE) and a last-write time only, LZMA2 with no BCJ
    filter, members in name order. py7zr >= 1.1 adds Unix-extension attribute
    bits (0x8000 | mode << 16) and creation/access times to every entry — and
    SensorView 15.14 either hangs on such a file or fails its import with
    "Could not find file ...\\WebUI\\Maps\\mapNNNN.json" (seen 2026-10-21).
    Keeping the entries plain is what makes the export importable.
    """

    EXPORT_FILTERS = [{"id": py7zr.FILTER_LZMA2, "preset": 7}]

    def __init__(self, file, mode="w", **kwargs):
        kwargs.setdefault("filters", self.EXPORT_FILTERS)
        super().__init__(file, mode, **kwargs)

    @staticmethod
    def _plain(info):
        info["attributes"] = 32
        info.pop("creationtime", None)
        info.pop("lastaccesstime", None)
        return info

    @staticmethod
    def _make_file_info(target, arcname=None, dereference=False):
        return ExportArchive._plain(py7zr.SevenZipFile._make_file_info(target, arcname, dereference))

    @staticmethod
    def _make_file_info_from_name(bio, size, arcname):
        return ExportArchive._plain(py7zr.SevenZipFile._make_file_info_from_name(bio, size, arcname))

try:
    from . import dblabels  # installed package / py -m mapview_editor
except ImportError:
    import dblabels  # direct run: py mapview_editor/server.py, and PyInstaller

# When frozen by PyInstaller, bundled data lives under sys._MEIPASS, not the cwd.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

app = Flask(
    __name__,
    static_folder=str(BASE_DIR / "static"),
    template_folder=str(BASE_DIR / "templates"),
)

WORK_DIR = None
MAP_DATA = {}
MAP_INFO = {"version": 1, "maps": []}
# Read-only database labels live in their own temp dir, never WORK_DIR: the
# Access driver drops a sensor.ldb lock next to the .mdb, and the export loop
# must never be able to see it.
LABELS = None
LABELS_SOURCE = None
LABELS_DIR = None
# Bumped on every mutation. The browser polls it and reloads when something
# else (the MCP server, curl, another tab) changes the maps, so external edits
# appear live. Mutating responses include the new value so the browser can
# tell its own writes apart from external ones.
REVISION = 0
REPO_DIR = Path(__file__).resolve().parent


def _bump_revision():
    global REVISION
    REVISION += 1
    return REVISION


def get_work_dir():
    global WORK_DIR
    if WORK_DIR is None or not Path(WORK_DIR).exists():
        WORK_DIR = tempfile.mkdtemp(prefix="mvdb_edit_")
    return WORK_DIR


def _git(*args):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR / "templates"), "index.html")


@app.route("/api/version")
def get_version():
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    commit = _git("rev-parse", "--short", "HEAD")
    commit_date = _git("log", "-1", "--format=%ci")
    dirty = bool(_git("status", "--porcelain"))
    return jsonify(
        version=__version__,
        branch=branch or "unknown",
        commit=commit or "unknown",
        commitDate=commit_date,
        dirty=dirty,
    )


@app.route("/api/upload", methods=["POST"])
def upload_mvdb():
    """Extract an uploaded .mvdb and load it into memory."""
    global MAP_INFO, MAP_DATA

    f = request.files.get("file")
    if not f:
        return jsonify(error="No file uploaded"), 400

    work = get_work_dir()
    for item in Path(work).iterdir():
        if item.is_file():
            item.unlink()

    archive_bytes = f.read()
    with py7zr.SevenZipFile(io.BytesIO(archive_bytes), "r") as z:
        z.extractall(path=work)

    mapinfo_path = Path(work) / "mapinfo"
    if mapinfo_path.exists():
        MAP_INFO = json.loads(mapinfo_path.read_text(encoding="utf-8"))
    else:
        MAP_INFO = {"version": 1, "maps": []}

    MAP_DATA = {}
    for entry in MAP_INFO.get("maps", []):
        fkey = entry["file"]
        json_path = Path(work) / f"{fkey}.json"
        if json_path.exists() and json_path.stat().st_size > 0:
            try:
                MAP_DATA[fkey] = json.loads(json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                MAP_DATA[fkey] = {"width": 4000, "height": 3000, "zones": [], "subzones": [], "devices": []}
        else:
            MAP_DATA[fkey] = {"width": 4000, "height": 3000, "zones": [], "subzones": [], "devices": []}

    return jsonify(ok=True, mapinfo=_mapinfo_payload(), revision=_bump_revision())


def _maps_without_image():
    """Map keys listed in mapinfo that have no PNG in the working folder.
    SensorView will not load an archive whose map lacks its image, so the
    export refuses these and the UI flags them."""
    work = get_work_dir()
    return [e["file"] for e in MAP_INFO.get("maps", [])
            if not (Path(work) / f"{e['file']}.png").exists()]


# ─── Map index helpers (drop-down order in SensorView = mapinfo order) ───

_LEVEL_RE = re.compile(r"^LEVEL\s+(P\d+|B\d*|PH|\d{1,2})(?:\s*[-_ ]\s*(.+))?$", re.I)


def level_sort_key(name):
    """Sort key so a building's maps read as a building does: parking levels,
    basement, floors 1..n, penthouse; anything unrecognised keeps its place
    after them, alphabetically."""
    m = _LEVEL_RE.match(str(name).strip())
    if not m:
        return (9, 0, str(name).upper())
    lvl, rest = m.group(1).upper(), (m.group(2) or "").upper()
    if lvl == "PH":
        return (3, 0, rest)
    if lvl.startswith("P"):
        return (0, int(lvl[1:] or 0), rest)
    if lvl.startswith("B"):
        return (1, int(lvl[1:] or 0), rest)
    return (2, int(lvl), rest)


def normalize_map_name(name):
    """Collapse whitespace and write level names the way SensorView's own maps
    are named: 'LEVEL 05', 'LEVEL P1', 'LEVEL 01 - LOBBY'."""
    name = re.sub(r"\s+", " ", str(name)).strip()
    m = _LEVEL_RE.match(name)
    if not m:
        return name
    lvl, rest = m.group(1).upper(), (m.group(2) or "").strip()
    if lvl.isdigit():
        lvl = f"{int(lvl):02d}"
    return f"LEVEL {lvl}" + (f" - {rest.upper()}" if rest else "")


def _ordered_entry(e):
    """mapinfo entries in the export's key order: file, type, group, name."""
    out = {"file": e["file"], "type": e.get("type", 1),
           "group": str(e.get("group", "")).strip(), "name": re.sub(r"\s+", " ", str(e.get("name", ""))).strip()}
    for k, v in e.items():
        if k not in out:
            out[k] = v
    return out


@app.route("/api/revision")
def get_revision():
    return jsonify(revision=REVISION, labelsSource=LABELS_SOURCE)


def _label_stats():
    """Count how many map devices/zones have a label in the loaded database."""
    md = td = mz = tz = 0
    for data in MAP_DATA.values():
        for d in data.get("devices", []):
            td += 1
            if str(d.get("id", "")).strip().upper() in LABELS["devices"]:
                md += 1
        for z in data.get("zones", []):
            tz += 1
            key = f"{str(z.get('ParentDeviceID', '')).strip().upper()}:{z.get('Port')}"
            if str(z.get("id")) in LABELS["zones"] or key in LABELS["zonesByParent"]:
                mz += 1
    return {"devicesMatched": md, "devicesTotal": td,
            "zonesMatched": mz, "zonesTotal": tz}


@app.route("/api/labels", methods=["POST"])
def upload_labels():
    """Load a SensorView database (.svdb/.svdo/.mdb) read-only for display labels."""
    global LABELS, LABELS_SOURCE, LABELS_DIR

    f = request.files.get("file")
    if not f:
        return jsonify(error="No file uploaded"), 400

    new_dir = tempfile.mkdtemp(prefix="mvdb_labels_")
    staged = Path(new_dir) / Path(f.filename).name
    f.save(str(staged))
    try:
        mdb = dblabels.stage_mdb(str(staged), new_dir)
        labels = dblabels.read_labels(mdb)  # connection closed inside
    except dblabels.LabelsUnavailable as e:
        shutil.rmtree(new_dir, ignore_errors=True)
        return jsonify(error=str(e), unavailable=True), 503
    except Exception as e:
        shutil.rmtree(new_dir, ignore_errors=True)
        return jsonify(error=f"Could not read database: {e}"), 400

    if LABELS_DIR:
        shutil.rmtree(LABELS_DIR, ignore_errors=True)
    LABELS_DIR, LABELS, LABELS_SOURCE = new_dir, labels, Path(f.filename).name
    return jsonify(ok=True, source=LABELS_SOURCE, stats=_label_stats(),
                   revision=_bump_revision(), **labels)


@app.route("/api/labels")
def get_labels():
    if LABELS is None:
        return jsonify(loaded=False)
    return jsonify(loaded=True, source=LABELS_SOURCE, stats=_label_stats(), **LABELS)


@app.route("/api/labels", methods=["DELETE"])
def clear_labels():
    global LABELS, LABELS_SOURCE, LABELS_DIR
    if LABELS_DIR:
        shutil.rmtree(LABELS_DIR, ignore_errors=True)
    LABELS = LABELS_SOURCE = LABELS_DIR = None
    return jsonify(ok=True, revision=_bump_revision())


@app.route("/api/index")
def device_index():
    """Compact index of every device marker across all maps, for search."""
    out = []
    for entry in MAP_INFO.get("maps", []):
        fkey = entry["file"]
        for d in MAP_DATA.get(fkey, {}).get("devices", []):
            out.append({"id": d.get("id"), "map": fkey,
                        "x": d.get("x"), "y": d.get("y")})
    return jsonify(devices=out)


def _mapinfo_payload():
    """The map index plus which maps still lack a floorplan image."""
    return {"version": MAP_INFO.get("version", 1), "maps": MAP_INFO["maps"],
            "missingImages": _maps_without_image()}


@app.route("/api/mapinfo")
def get_mapinfo():
    return jsonify(_mapinfo_payload())


@app.route("/api/mapinfo", methods=["PUT"])
def update_mapinfo():
    """Replace the full map index (reorder, rename, regroup entries).

    The order of `maps` is the order SensorView shows in its MapView drop-down.
    Entries are matched by file key; a key that is not currently loaded is
    rejected so a stale client cannot resurrect a deleted map or invent one."""
    global MAP_INFO
    data = request.get_json()
    if not data or "maps" not in data:
        return jsonify(error="Body must be {maps: [...]}"), 400
    known = {e["file"] for e in MAP_INFO["maps"]}
    incoming = [e.get("file") for e in data["maps"]]
    unknown = [k for k in incoming if k not in known]
    missing = sorted(known - set(incoming))
    if unknown or missing or len(set(incoming)) != len(incoming):
        return jsonify(error="maps must list every loaded map exactly once",
                       unknown=unknown, missing=missing), 400
    MAP_INFO["maps"] = [_ordered_entry(e) for e in data["maps"]]
    _save_mapinfo()
    return jsonify(ok=True, mapinfo=_mapinfo_payload(), revision=_bump_revision())


@app.route("/api/mapinfo/sort", methods=["POST"])
def sort_mapinfo():
    """Sort every building group by level (P1, B, 01 … 12, PH); groups keep
    their current order. With {"normalize": true} map names are also rewritten
    in the export's style ('Level 12' → 'LEVEL 12', 'Level 01_Lobby' →
    'LEVEL 01 - LOBBY')."""
    global MAP_INFO
    data = request.get_json(silent=True) or {}
    maps = [_ordered_entry(e) for e in MAP_INFO["maps"]]
    renamed = []
    if data.get("normalize"):
        for e in maps:
            new = normalize_map_name(e["name"])
            if new != e["name"]:
                renamed.append({"file": e["file"], "from": e["name"], "to": new})
                e["name"] = new
    groups = []
    for e in maps:
        if e["group"] not in groups:
            groups.append(e["group"])
    ordered = []
    for g in groups:
        ordered += sorted((e for e in maps if e["group"] == g), key=lambda e: level_sort_key(e["name"]))
    MAP_INFO["maps"] = ordered
    _save_mapinfo()
    return jsonify(ok=True, mapinfo=_mapinfo_payload(), renamed=renamed, revision=_bump_revision())


@app.route("/api/map/<file_key>/image")
def get_map_image(file_key):
    work = get_work_dir()
    img_path = Path(work) / f"{file_key}.png"
    if not img_path.exists():
        return jsonify(error="Image not found"), 404
    return send_file(img_path, mimetype="image/png")


@app.route("/api/map/<file_key>/image", methods=["POST"])
def upload_map_image(file_key):
    """Replace the floorplan PNG for a map."""
    f = request.files.get("image")
    if not f:
        return jsonify(error="No image uploaded"), 400

    work = get_work_dir()
    img_path = Path(work) / f"{file_key}.png"
    f.save(str(img_path))

    try:
        from PIL import Image
        with Image.open(img_path) as img:
            w, h = img.size
    except Exception:
        w, h = None, None

    if file_key in MAP_DATA and w and h:
        MAP_DATA[file_key]["width"] = w
        MAP_DATA[file_key]["height"] = h
        _save_map_json(file_key)

    return jsonify(ok=True, width=w, height=h, revision=_bump_revision())


@app.route("/api/map/<file_key>/data")
def get_map_data(file_key):
    if file_key in MAP_DATA:
        return jsonify(MAP_DATA[file_key])
    work = get_work_dir()
    json_path = Path(work) / f"{file_key}.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        MAP_DATA[file_key] = data
        return jsonify(data)
    return jsonify(error="Map data not found"), 404


@app.route("/api/map/<file_key>/data", methods=["PUT"])
def update_map_data(file_key):
    """Save updated map JSON (devices, zones, metadata)."""
    data = request.get_json()
    if not data:
        return jsonify(error="No data"), 400
    MAP_DATA[file_key] = data
    _save_map_json(file_key)
    return jsonify(ok=True, revision=_bump_revision())


@app.route("/api/map/create", methods=["POST"])
def create_map():
    """Create a new map entry."""
    global MAP_INFO
    data = request.get_json()
    group = data.get("group", "NEW")
    name = data.get("name", "Untitled")

    existing_ids = [int(e["file"].replace("map", "")) for e in MAP_INFO["maps"]]
    next_id = max(existing_ids, default=0) + 1
    file_key = f"map{next_id:04d}"

    MAP_INFO["maps"].append({
        "file": file_key,
        "type": 1,
        "group": group,
        "name": name,
    })
    _save_mapinfo()

    MAP_DATA[file_key] = {
        "width": 4000,
        "height": 3000,
        "zoomLevels": 9,
        "resolutionMin": 80,
        "resolutionMax": 800,
        "deviceScale": 20,
        "zones": [],
        "subzones": [],
        "devices": [],
    }
    _save_map_json(file_key)
    return jsonify(ok=True, file=file_key, mapinfo=_mapinfo_payload(), revision=_bump_revision())


@app.route("/api/map/<file_key>", methods=["DELETE"])
def delete_map(file_key):
    """Remove a map from the archive."""
    global MAP_INFO
    MAP_INFO["maps"] = [m for m in MAP_INFO["maps"] if m["file"] != file_key]
    _save_mapinfo()
    MAP_DATA.pop(file_key, None)

    work = get_work_dir()
    for ext in (".json", ".png"):
        p = Path(work) / f"{file_key}{ext}"
        if p.exists():
            p.unlink()

    return jsonify(ok=True, mapinfo=_mapinfo_payload(), revision=_bump_revision())


def _optimize_png(fpath):
    """Convert a floorplan PNG to indexed/palette mode for lossless size reduction.

    Floorplan exports are flat-color line art (line, fill, background) already
    quantized to a small palette but saved as 24-bit RGB. Re-encoding as 8-bit
    indexed PNG is pixel-identical and typically ~55-60% smaller.
    Returns the optimized bytes, or the original bytes if optimization isn't
    possible (Pillow missing, image already indexed, non-PNG content, etc.).
    """
    original_bytes = fpath.read_bytes()
    try:
        from PIL import Image
    except ImportError:
        return original_bytes

    try:
        img = Image.open(io.BytesIO(original_bytes))
        if img.mode == "P":
            return original_bytes  # already indexed

        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        rgb = img.convert("RGBA" if has_alpha else "RGB")

        colors = rgb.getcolors(maxcolors=256)
        if colors is None:
            return original_bytes  # more than 256 colors — indexing would be lossy, skip

        pal_img = rgb.convert("P", palette=Image.ADAPTIVE, colors=256)
        out = io.BytesIO()
        pal_img.save(out, format="PNG", optimize=True, compress_level=9)
        optimized = out.getvalue()
        return optimized if len(optimized) < len(original_bytes) else original_bytes
    except Exception:
        return original_bytes


def _export_map_json(fkey):
    """Per-map JSON as SensorView writes it: device x/y as integers (the
    export never carries decimals; the editor's drag and the MCP tools can
    leave fractions), keys in the export's order. Zone WKT keeps its floats —
    SensorView itself writes those."""
    data = MAP_DATA.get(fkey, {})
    devices = []
    for d in data.get("devices", []):
        nd = dict(d)
        for ax in ("x", "y"):
            if isinstance(nd.get(ax), float):
                nd[ax] = int(round(nd[ax]))
        devices.append(nd)
    order = ["width", "height", "zoomLevels", "resolutionMin", "resolutionMax",
             "deviceScale", "zones", "subzones", "devices"]
    out = {k: data[k] for k in order if k in data}
    out["devices"] = devices
    for k, v in data.items():
        if k not in out:
            out[k] = v
    return json.dumps(out, separators=(",", ":")).encode("utf-8")


@app.route("/api/export", methods=["POST"])
def export_mvdb():
    """Repackage the working directory as a downloadable .mvdb, optimizing PNGs.

    Refuses to export while a map in the index has no floorplan image:
    SensorView does not load an archive with a map whose PNG is missing, and
    a silent omission was how a broken export reached a live site (2026-10-21).
    """
    work = get_work_dir()

    _save_mapinfo()
    for fkey, data in MAP_DATA.items():
        _save_map_json(fkey)

    missing = _maps_without_image()
    if missing:
        names = [f"{e.get('name', '')} ({e['file']})" for e in MAP_INFO["maps"] if e["file"] in missing]
        return jsonify(error="Every map needs a floorplan image before export. "
                             "Add an image or delete: " + ", ".join(names),
                       missingImages=missing), 409

    stats = {"before": 0, "after": 0}

    # Stage the exact bytes to ship, then add them in name order (the shape of
    # SensorView's own export — see ExportArchive).
    stage = Path(tempfile.mkdtemp(prefix="mvdb_export_"))
    try:
        members = []
        for entry in MAP_INFO["maps"]:
            fkey = entry["file"]
            jp = stage / f"{fkey}.json"
            jp.write_bytes(_export_map_json(fkey))
            members.append((jp, f"{fkey}.json"))

            png_path = Path(work) / f"{fkey}.png"
            before_size = png_path.stat().st_size
            optimized_bytes = _optimize_png(png_path)
            stats["before"] += before_size
            stats["after"] += len(optimized_bytes)
            pp = stage / f"{fkey}.png"
            pp.write_bytes(optimized_bytes)
            members.append((pp, f"{fkey}.png"))

        mp = stage / "mapinfo"
        mp.write_bytes(json.dumps(
            {"version": MAP_INFO.get("version", 1), "maps": [_ordered_entry(e) for e in MAP_INFO["maps"]]},
            separators=(",", ":")).encode("utf-8"))
        members.append((mp, "mapinfo"))
        members.sort(key=lambda m: m[1])

        buf = io.BytesIO()
        with ExportArchive(buf, "w") as z:
            for path, arcname in members:
                z.write(path, arcname)
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    buf.seek(0)
    response = send_file(
        buf,
        mimetype="application/x-7z-compressed",
        as_attachment=True,
        download_name="MapViewExport_edited.mvdb",
    )
    response.headers["X-Images-Before-Bytes"] = str(stats["before"])
    response.headers["X-Images-After-Bytes"] = str(stats["after"])
    return response


def _save_mapinfo():
    work = get_work_dir()
    path = Path(work) / "mapinfo"
    MAP_INFO["maps"] = [_ordered_entry(e) for e in MAP_INFO.get("maps", [])]
    path.write_text(json.dumps(MAP_INFO, separators=(",", ":")), encoding="utf-8")


def _save_map_json(file_key):
    work = get_work_dir()
    path = Path(work) / f"{file_key}.json"
    path.write_text(
        json.dumps(MAP_DATA.get(file_key, {}), separators=(",", ":")),
        encoding="utf-8",
    )


def main():
    print(f"MapView Editor v{__version__} running at http://localhost:5111")
    # debug/reloader off: the reloader re-executes the process, which breaks
    # PyInstaller onefile builds (and debug tracebacks aren't for end users).
    Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5111")).start()
    app.run(host="127.0.0.1", port=5111, debug=False)


if __name__ == "__main__":
    main()
