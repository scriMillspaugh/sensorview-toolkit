"""
SensorView Backup Relabeler — command-line interface.

Applies a rename list (crosswalk CSVs) to a SensorView .svdb backup and writes a
new _relabeled.svdb. Same engine as the web tool (core.py); the original file is
never modified.

Usage:
  py cli.py backup.svdb --devices devices.csv                 # dry-run (default)
  py cli.py backup.svdb --devices devices.csv --zones zones.csv --apply

CSV formats:
  devices.csv : DeviceID,CurrentLabel,ProposedLabel   (blank ProposedLabel = unchanged)
  zones.csv   : ZoneID,CurrentName,ProposedName        (blank ProposedName  = unchanged)
See examples/ for templates.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile

import core


def load_map(path, id_col, label_col):
    out = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if id_col not in reader.fieldnames or label_col not in reader.fieldnames:
            sys.exit(f"{path}: needs columns '{id_col}' and '{label_col}'")
        for row in reader:
            label = (row[label_col] or "").strip()
            if label:
                out[(row[id_col] or "").strip()] = label
    return out


def main():
    ap = argparse.ArgumentParser(description="Relabel a SensorView .svdb from crosswalk CSVs.")
    ap.add_argument("svdb", help="Path to the .svdb backup")
    ap.add_argument("--devices", help="Device rename CSV (DeviceID,CurrentLabel,ProposedLabel)")
    ap.add_argument("--zones", help="Zone rename CSV (ZoneID,CurrentName,ProposedName)")
    ap.add_argument("--apply", action="store_true", help="Write changes (default is a dry-run)")
    args = ap.parse_args()

    if not args.devices and not args.zones:
        sys.exit("Provide --devices and/or --zones.")

    dev_map = load_map(args.devices, "DeviceID", "ProposedLabel") if args.devices else {}
    zone_map = load_map(args.zones, "ZoneID", "ProposedName") if args.zones else {}
    print(f"Loaded {len(dev_map)} device + {len(zone_map)} zone labels.")

    problems = core.validate(dev_map, zone_map)
    if problems:
        print(f"\nVALIDATION FAILED ({len(problems)}):")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("Validation passed (BMS rules, no duplicates, valid floors).")

    # Report coverage against the actual backup contents.
    tmp = tempfile.mkdtemp(prefix="svcli_")
    mdb, _ = core.extract_svdb(args.svdb, tmp)
    tables = core.read_tables(mdb)
    dev_ids = {d["id"] for d in tables["devices"]}
    zone_ids = {z["id"] for z in tables["zones"]}
    dmatch = len(dev_map.keys() & dev_ids)
    zmatch = len(zone_map.keys() & zone_ids)
    print(f"Backup has {len(dev_ids)} devices, {len(zone_ids)} zones.")
    print(f"  {dmatch}/{len(dev_map)} device labels match a device in the backup.")
    print(f"  {zmatch}/{len(zone_map)} zone labels match a zone in the backup.")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write a _relabeled.svdb.")
        return

    stem = os.path.splitext(os.path.basename(args.svdb))[0]
    out_path = os.path.join(os.path.dirname(os.path.abspath(args.svdb)), f"{stem}_relabeled.svdb")
    summary = core.relabel(args.svdb, dev_map, zone_map, out_path)
    print(f"\nWrote {out_path}")
    print(f"Updated {summary['devices_changed']} devices + {summary['zones_changed']} zones.")
    print("Import it in SensorView (Import -> Synchronize if needed -> do NOT Clear).")


if __name__ == "__main__":
    main()
