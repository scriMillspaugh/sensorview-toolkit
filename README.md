# SensorView Toolkit

Local, browser-based utilities for working with **Acuity nLight SensorView**
export files. Everything runs on your own machine — no cloud, no accounts, and
your exports never leave the PC.

> **Unofficial community toolkit.** Not an Acuity Brands product and not
> affiliated with or endorsed by Acuity. SensorView, nLight, and MapView are
> trademarks of their respective owners. Always keep your original export
> files and review results before importing.

## The tools

| Tool | Works on | What it does |
|---|---|---|
| [**Relabeler**](relabeler/) | `.svdb` (database backup) | Batch-rename device and zone labels from a rename list (in-browser editor or CSV), validate against BMS naming rules, rebuild the backup for re-import. Includes a CLI. |
| [**MapView Editor**](mapview-editor/) | `.mvdb` (MapView export) | Edit floorplans in the browser: move/add/remove device markers, draw and reshape zone polygons, rename/add/delete maps, swap floorplan images, auto-optimize PNGs on export. |

Both tools follow the same pattern:

```
export from SensorView ──► edit locally ──► rebuilt file ──► import into SensorView
        (original file is never modified)
```

## Quick start

```bash
pip install -r relabeler/requirements.txt -r mapview-editor/requirements.txt
```

**Relabeler** (labels): `python relabeler/app.py` → opens http://127.0.0.1:5000
**MapView Editor** (floorplans): `python mapview-editor/server.py` → open http://localhost:5111

They use different ports, so you can run both at once.

### Extra requirement for the Relabeler
The Relabeler opens the backup's Microsoft Access database, which needs the free
**Microsoft Access Database Engine** installed (one-time, per PC):
<https://www.microsoft.com/en-us/download/details.aspx?id=54920>
Match its bitness (64-bit Python → 64-bit engine). The MapView Editor has no such
requirement.

## Why local-only matters

A SensorView `.svdb` backup contains a `Users` table with **hashed passwords**,
and both file types describe your building layout and device network. These
files should never be uploaded to third-party services. Both tools bind to
localhost and do all processing on your machine.

## Docs

- [`relabeler/METHOD.md`](relabeler/METHOD.md) — how the backup → relabel →
  rebuild process works under the hood (file format, two-column label sync,
  ODBC editing, safe repackaging, import steps).
- [`mapview-editor/METHOD.md`](mapview-editor/METHOD.md) — the `.mvdb` format
  and edit pipeline (mapinfo index, per-map JSON, device markers vs zone WKT
  polygons and the y-flip trap, safe repack, PNG optimization).
- [`mapview-editor/FLOORPLAN_STANDARD.md`](mapview-editor/FLOORPLAN_STANDARD.md) —
  floorplan image guidelines (one map per floor, indexed-color PNG, ~55–60%
  size savings).

## License

MIT — see [LICENSE](LICENSE).
