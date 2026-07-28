"""
SensorView Backup Relabeler — command-line interface.

Applies a rename list (crosswalk CSVs) to a SensorView .svdb backup and writes a
new _relabeled.svdb. Same engine as the web tool (core.py); the original file is
never modified.

Usage:
  py cli.py backup.svdb --devices devices.csv                 # dry-run (default); also accepts a bare sensor.mdb
  py cli.py backup.svdb --devices devices.csv --zones zones.csv --apply

CSV formats:
  devices.csv : DeviceID,CurrentLabel,ProposedLabel[,Notes]  (blank = unchanged)
  zones.csv   : ZoneID,CurrentName,ProposedName[,Notes]      (blank = unchanged)
The Notes column is optional and maps to SensorView's UserComments (200 chars).
See examples/ for templates.

Labeling rules and the recommended naming format:
  https://github.com/scriMillspaugh/sensorview-toolkit/blob/main/LABELING.md
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile

import core


def load_map(path, id_col, label_col):
    """Read a rename CSV. Returns (labels, notes) — notes come from an optional
    'Notes' (or 'UserComments') column and are absent if it isn't present."""
    labels, notes = {}, {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if id_col not in reader.fieldnames or label_col not in reader.fieldnames:
            sys.exit(f"{path}: needs columns '{id_col}' and '{label_col}'")
        note_col = next((c for c in reader.fieldnames if c.strip().lower() in ("notes", "usercomments")), None)
        for row in reader:
            rid = (row[id_col] or "").strip()
            label = (row[label_col] or "").strip()
            if label:
                labels[rid] = label
            if note_col and rid:
                note = (row[note_col] or "").strip()
                if note:
                    notes[rid] = note
    return labels, notes


def main():
    ap = argparse.ArgumentParser(description="Relabel a SensorView .svdb backup (or bare sensor.mdb) from crosswalk CSVs.")
    ap.add_argument("--version", action="version", version=f"relabeler {core.__version__}")
    ap.add_argument("svdb", help="Path to the .svdb backup (or a bare sensor.mdb database)")
    ap.add_argument("--devices", help="Device rename CSV (DeviceID,CurrentLabel,ProposedLabel)")
    ap.add_argument("--zones", help="Zone rename CSV (ZoneID,CurrentName,ProposedName)")
    ap.add_argument("--apply", action="store_true", help="Write changes (default is a dry-run)")
    args = ap.parse_args()

    if not args.devices and not args.zones:
        sys.exit("Provide --devices and/or --zones.")

    dev_map, dev_notes = load_map(args.devices, "DeviceID", "ProposedLabel") if args.devices else ({}, {})
    zone_map, zone_notes = load_map(args.zones, "ZoneID", "ProposedName") if args.zones else ({}, {})
    print(f"Loaded {len(dev_map)} device + {len(zone_map)} zone labels.")

    problems = core.validate(dev_map, zone_map, dev_notes, zone_notes)
    if problems:
        print(f"\nVALIDATION FAILED ({len(problems)}):")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("Validation passed (BACnet rules, SensorView limits, no duplicates).")

    advisories = core.advisories(dev_map, zone_map)
    if advisories:
        print(f"\nNOTES ({len(advisories) - 1}) — recommended practice only, not blocking:")
        for a in advisories:
            print("  -", a)

    # Report coverage against the actual backup contents.
    tmp = tempfile.mkdtemp(prefix="svcli_")
    mdb, _ = core.prepare_input(args.svdb, tmp)
    tables = core.read_tables(mdb)
    dev_ids = {d["id"] for d in tables["devices"]}
    zone_ids = {z["id"] for z in tables["zones"]}
    dmatch = len(dev_map.keys() & dev_ids)
    zmatch = len(zone_map.keys() & zone_ids)
    print(f"Backup has {len(dev_ids)} devices, {len(zone_ids)} zones.")
    print(f"  {dmatch}/{len(dev_map)} device labels match a device in the backup.")
    print(f"  {zmatch}/{len(zone_map)} zone labels match a zone in the backup.")

    # Drop notes that already match the backup, so re-running an unedited export
    # doesn't report writes it isn't really making.
    for cur_map, incoming in ((tables["devices"], dev_notes), (tables["zones"], zone_notes)):
        existing = {r["id"]: r["notes"] for r in cur_map}
        for rid in [k for k, v in incoming.items() if existing.get(k, "") == v]:
            del incoming[rid]
    if dev_notes or zone_notes:
        print(f"  {len(dev_notes)} device + {len(zone_notes)} zone note(s) changed.")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write a _relabeled.svdb.")
        return

    stem, ext = os.path.splitext(os.path.basename(args.svdb))
    ext = ext or ".svdb"  # output mirrors the input type
    out_path = os.path.join(os.path.dirname(os.path.abspath(args.svdb)), f"{stem}_relabeled{ext}")
    summary = core.relabel(args.svdb, dev_map, zone_map, out_path, dev_notes, zone_notes)
    print(f"\nWrote {out_path}")
    print(f"Updated {summary['devices_changed']} devices + {summary['zones_changed']} zones.")
    print("Import it in SensorView (Import -> Synchronize if needed -> do NOT Clear).")


if __name__ == "__main__":
    main()
