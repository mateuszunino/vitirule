#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/download_sensor_datasets.py
===================================
Downloads the two open leaf-wetness sensor datasets directly from their
official DOIs into `data/lwd_sensors/` (which is `.gitignore`d so raw
third-party data are never redistributed in the repository):

1. INRAE AgroClim (DOI: 10.57745/BQ0BWB) — 4 French viticultural stations
   via Recherche Data Gouv Dataverse API.
2. Politecnico di Torino / iXem Labs (DOI: 10.17632/sd4b8vpvyb.1) —
   7 Italian sites via Mendeley Data public API (License: CC BY-NC 4.0).

Usage:
    python scripts/download_sensor_datasets.py --dry-run
    python scripts/download_sensor_datasets.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
INRAE_DIR = ROOT / "data" / "lwd_sensors" / "inrae"
POLITO_DIR = ROOT / "data" / "lwd_sensors" / "polito"

INRAE_DOI = "doi:10.57745/BQ0BWB"
INRAE_META_URL = f"https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId={INRAE_DOI}"
INRAE_FILE_URL = "https://entrepot.recherche.data.gouv.fr/api/access/datafile/{file_id}"

INRAE_STATION_MAP = {
    "33080002": "33080002_bordeaux_couhins.tab",
    "68066002": "68066002_alsace_colmar.tab",
    "51242002": "51242002_champagne_fagnieres.tab",
    "21106002": "21106002_bourgogne_breteniere.tab",
}

POLITO_META_URL = "https://data.mendeley.com/public-api/datasets/sd4b8vpvyb?version=1"
POLITO_FILES_URL = "https://data.mendeley.com/public-api/datasets/sd4b8vpvyb/files?folder_id=root&version=1"
HEADERS = {"User-Agent": "grapevine-downy-mildew-eval/1.0"}


def _download_stream(url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = 0
        with dest.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
                    total += len(chunk)
    return total


def fetch_inrae(dry_run: bool = False, force: bool = False) -> None:
    try:
        resp = requests.get(INRAE_META_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[INRAE AgroClim | {INRAE_DOI}] Unavailable ({exc}). Retry later or download manually from https://doi.org/10.57745/BQ0BWB")
        return
    payload = resp.json()["data"]["latestVersion"]
    lic = payload.get("license", {})
    lic_name = lic.get("name") if isinstance(lic, dict) else str(lic)
    lic_uri = lic.get("uri", "") if isinstance(lic, dict) else ""
    print(f"[INRAE AgroClim | {INRAE_DOI}] License: {lic_name} ({lic_uri})")

    files = payload.get("files", [])
    matched = 0
    for f in files:
        df = f.get("dataFile", {})
        fname = df.get("filename", "")
        fid = df.get("id")
        for st_id, target_name in INRAE_STATION_MAP.items():
            if st_id in fname and ("h" in fname.lower()):
                if "quotidien" in fname.lower() or f"q_{st_id}" in fname.lower() or f"{st_id}_q" in fname.lower():
                    continue
                dest = INRAE_DIR / target_name
                matched += 1
                if dry_run:
                    print(f"  [dry-run] {fname} (id={fid}) -> {dest.relative_to(ROOT)} (exists={dest.is_file()})")
                elif dest.is_file() and not force:
                    print(f"  [skip] {dest.relative_to(ROOT)} already exists")
                else:
                    nbytes = _download_stream(INRAE_FILE_URL.format(file_id=fid), dest)
                    print(f"  [ok]   {dest.relative_to(ROOT)} ({nbytes:,} bytes)")
                break
    if matched < len(INRAE_STATION_MAP):
        print(f"  [warn] Matched {matched}/{len(INRAE_STATION_MAP)} INRAE hourly station files.")


def fetch_polito(dry_run: bool = False, force: bool = False) -> None:
    try:
        m_resp = requests.get(POLITO_META_URL, headers=HEADERS, timeout=30)
        m_resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Politecnico di Torino | doi:10.17632/sd4b8vpvyb.1] Unavailable ({exc}).")
        return
    meta = m_resp.json()
    lic = meta.get("data_licence") or meta.get("licence") or meta.get("license") or {}
    lic_name = lic.get("short_name") or lic.get("name") if isinstance(lic, dict) else str(lic)
    lic_url = lic.get("url", "") if isinstance(lic, dict) else ""
    print(f"[Politecnico di Torino | doi:10.17632/sd4b8vpvyb.1] License: {lic_name} ({lic_url})")

    try:
        f_resp = requests.get(POLITO_FILES_URL, headers=HEADERS, timeout=30)
        f_resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [warn] Could not list Politecnico files ({exc}).")
        return
    for item in f_resp.json():
        fname = item.get("filename", "")
        dl_url = (item.get("content_details") or {}).get("download_url")
        if not fname or not dl_url:
            continue
        dest = POLITO_DIR / Path(fname).name
        if dry_run:
            print(f"  [dry-run] {fname} -> {dest.relative_to(ROOT)} (exists={dest.is_file()})")
        elif dest.is_file() and not force:
            print(f"  [skip] {dest.relative_to(ROOT)} already exists")
        else:
            nbytes = _download_stream(dl_url, dest)
            print(f"  [ok]   {dest.relative_to(ROOT)} ({nbytes:,} bytes)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download real LWD sensor datasets from their official DOIs.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect licenses and file URLs without downloading.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing local files.")
    args = parser.parse_args(argv)

    fetch_inrae(dry_run=args.dry_run, force=args.force)
    fetch_polito(dry_run=args.dry_run, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
