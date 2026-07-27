"""MapView Editor — local Flask server for editing .mvdb floorplan archives."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path
from threading import Timer

import py7zr
from flask import Flask, jsonify, request, send_file, send_from_directory

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
REPO_DIR = Path(__file__).resolve().parent


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
        branch=branch or "unknown",
        commit=commit or "unknown",
        commitDate=commit_date,
        dirty=dirty,
        repoPath=str(REPO_DIR),
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

    return jsonify(ok=True, mapinfo=MAP_INFO)


@app.route("/api/mapinfo")
def get_mapinfo():
    return jsonify(MAP_INFO)


@app.route("/api/mapinfo", methods=["PUT"])
def update_mapinfo():
    """Replace the full map index (reorder, rename, delete entries)."""
    global MAP_INFO
    data = request.get_json()
    if data and "maps" in data:
        MAP_INFO["maps"] = data["maps"]
        _save_mapinfo()
    return jsonify(ok=True, mapinfo=MAP_INFO)


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

    return jsonify(ok=True, width=w, height=h)


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
    return jsonify(ok=True)


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
    return jsonify(ok=True, file=file_key, mapinfo=MAP_INFO)


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

    return jsonify(ok=True, mapinfo=MAP_INFO)


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


@app.route("/api/export", methods=["POST"])
def export_mvdb():
    """Repackage the working directory as a downloadable .mvdb, optimizing PNGs."""
    work = get_work_dir()

    _save_mapinfo()
    for fkey, data in MAP_DATA.items():
        _save_map_json(fkey)

    stats = {"before": 0, "after": 0}

    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as z:
        for entry in MAP_INFO["maps"]:
            fkey = entry["file"]

            json_path = Path(work) / f"{fkey}.json"
            if json_path.exists():
                z.write(json_path, f"{fkey}.json")

            png_path = Path(work) / f"{fkey}.png"
            if png_path.exists():
                before_size = png_path.stat().st_size
                optimized_bytes = _optimize_png(png_path)
                stats["before"] += before_size
                stats["after"] += len(optimized_bytes)
                z.writestr(optimized_bytes, f"{fkey}.png")

        mapinfo_path = Path(work) / "mapinfo"
        if mapinfo_path.exists():
            z.write(mapinfo_path, "mapinfo")

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
    path.write_text(json.dumps(MAP_INFO, separators=(",", ":")), encoding="utf-8")


def _save_map_json(file_key):
    work = get_work_dir()
    path = Path(work) / f"{file_key}.json"
    path.write_text(
        json.dumps(MAP_DATA.get(file_key, {}), separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    print("MapView Editor running at http://localhost:5111")
    # debug/reloader off: the reloader re-executes the process, which breaks
    # PyInstaller onefile builds (and debug tracebacks aren't for end users).
    Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5111")).start()
    app.run(host="127.0.0.1", port=5111, debug=False)
