# SensorView Backup Relabeler

A small, **local** utility for batch-renaming device and zone labels inside an
Acuity **SensorView** `.svdb` backup, then rebuilding the backup so the new
labels can be re-imported. Comes as a browser-based tool and a command-line
version — both use the same engine.

Labels in SensorView feed BACnet object names through the nLight ECLYPSE
controllers, so consistent, rules-compliant labels matter. This tool makes a
bulk rename safe and repeatable: you supply a **rename list**, it does the file
surgery, and you get a new backup to import.

> **Note:** This is a community/support utility, not an official Acuity product.
> Always keep your original backup and review results before importing.

## How it works
1. **Load** a `.svdb` backup — or a bare `sensor.mdb` database file — and it
   reads every device and zone with its current label.
2. **Provide new labels** — type them into the table (web tool), or fill in a
   CSV rename list (either tool).
3. **Validate** — checks the labeling rules (see below).
4. **Apply & download** a rebuilt `<name>_relabeled` file (same type as the
   input: `.svdb` in → `.svdb` out, `.mdb` in → `.mdb` out).
5. In SensorView: **Import** the `_relabeled.svdb` → **Synchronize** if the labels
   don't push to devices → do **NOT** use Clear (that wipes labels and refills them
   from the devices).

## Labeling rules enforced
These mirror the constraints that keep BACnet point names valid:
- Uses only letters, digits, and underscores; **starts with a letter**.
- **Maximum 20 characters.**
- **No duplicate** labels (devices and zones checked separately).
- Floor token (the second `_`-separated field, when present) is `01`–`12`, `P1`,
  or `PH` — a guard against a common room-number mis-parse. `Site`-level names are allowed.

## Safety model
- **Runs entirely on `localhost`.** The backup never leaves the machine. A SensorView
  backup's database includes a `Users` table with **hashed passwords**, so it should
  never be uploaded to a server or shared externally.
- **The original file is never modified** — output is always a new `_relabeled` copy.
- Machine-generated labels should still get a **human review** before you rely on them.

## Prerequisites
- **Microsoft Access Database Engine** (free) must be installed — the backup's database
  can't be opened without it: <https://www.microsoft.com/en-us/download/details.aspx?id=54920>
  Match its bitness to how you run the tool (the packaged `.exe` is 64-bit → install the
  64-bit engine).
- For running from source: Python 3.9+.

## Run — web tool
```
py -m pip install -r requirements.txt
py app.py
```
Opens `http://127.0.0.1:5000`. Load a backup, enter/upload labels, validate, download.

## Run — command line
```
py cli.py your_backup.svdb --devices devices.csv --zones zones.csv            # dry-run
py cli.py your_backup.svdb --devices devices.csv --zones zones.csv --apply    # write it
```
See `examples/` for the CSV formats.

## Build a standalone .exe (for PCs without Python)
```
py -m pip install pyinstaller
py -m PyInstaller --onefile --name SensorViewRelabeler --add-data "core.py;." app.py
```
Output: `dist/SensorViewRelabeler.exe`. It bundles Python and the Python
dependencies, but **not** the Access Database Engine (a system driver) — that is a
one-time per-PC install (see Prerequisites).

## Layout
| File | What |
|---|---|
| `core.py` | Relabel engine (extract → edit `sensor.mdb` → repackage). No web/UI deps. |
| `app.py` | Local web tool (Flask) + single-page UI. |
| `cli.py` | Command-line front-end. |
| `examples/` | Sample rename-list CSVs. |
| `METHOD.md` | How the backup / relabel / rebuild process works, in detail. |

## License
MIT — see the repository root [LICENSE](../LICENSE).
