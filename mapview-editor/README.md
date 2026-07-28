# MapView Editor

A local web utility for editing Acuity nLight MapView floorplan archives (`.mvdb` files).

Load an exported `.mvdb`, edit floorplans, devices, and zones in the browser, then export a modified `.mvdb` for reimport into SensorView.

## Features

- **Load / Export** `.mvdb` archives (7-zip format used by SensorView MapView)
- **Map management** — add, rename, delete floor maps
- **Device editing** — select, move, add, and remove device markers
- **Zone editing** — draw new zone polygons, reshape vertices, delete zones
- **Image replacement** — swap floorplan PNGs for any map
- **Automatic image optimization on export** — floorplan PNGs are losslessly re-encoded to indexed color where possible, typically ~55-60% smaller with no visual change (see [FLOORPLAN_STANDARD.md](docs/FLOORPLAN_STANDARD.md))
- **Properties panel** — edit device IDs, positions, zone IDs, parent devices, ports
- **Pan & zoom** — scroll to zoom, drag to pan, `F` to fit
- **Keyboard shortcuts** — `1`–`5` for tools, `Del` to delete, `Ctrl+S` to save

## Requirements

- Python 3.10+
- Flask
- py7zr
- Pillow (for image optimization on export — server still works without it, just skips optimization)

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
python server.py
```

Open http://localhost:5111 and drop a `.mvdb` file onto the page.

### Workflow

1. Export a `.mvdb` from SensorView (Admin > MapView > Export)
2. Load it into MapView Editor
3. Edit maps — consolidate sectors, reposition devices, redraw zones, replace images
4. Click **Export .mvdb** to download the modified archive
5. Import back into SensorView (Admin > MapView > Import)

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `1` | Select tool |
| `2` | Move device tool |
| `3` | Add device tool |
| `4` | Draw zone tool |
| `5` | Edit zone tool |
| `F` | Fit map to view |
| `Del` | Delete selected item |
| `Esc` | Deselect |
| `Ctrl+S` | Save current map |

## .mvdb format

See [METHOD.md](docs/METHOD.md) for the full format and edit-pipeline writeup. In short, a `.mvdb` is a 7-zip archive containing:

- `mapinfo` — JSON index listing all maps (file key, building group, floor name)
- `mapNNNN.json` — per-map JSON with device positions (hex ID + x/y) and zone polygons (WKT POLYGON coordinates)
- `mapNNNN.png` — floorplan background images

## Build a standalone .exe (for PCs without Python)

```
py -m pip install pyinstaller
py -m PyInstaller --clean --onefile --name "MapViewEditor-v$(py -c 'import server; print(server.__version__)')" --add-data "static;static" --add-data "templates;templates" server.py
```

Output: `dist/MapViewEditor-v<version>.exe` — for example `MapViewEditor-v1.0.1.exe`.
Double-clicking it starts the server and opens the browser. The UI assets are
bundled; no extra installs needed (unlike the Label Editor, this tool does not use
the Access Database Engine).

The version is read from `__version__` rather than typed, so the filename can never
drift from the build. (The `$(...)` form works in both PowerShell and bash.)

Two rules worth keeping:

- **The version belongs in the filename**, so a download in someone's Downloads
  folder identifies itself without being run. Never ship a bare `MapViewEditor.exe`.
- **Always pass `--clean`.** Otherwise PyInstaller reuses the `build/` cache, stops
  at `checking EXE`, and exits 0 having produced an unchanged binary. Confirm a
  real build by running the exe and reading back the version it reports.

## License

MIT — see the repository root [LICENSE](../LICENSE).
