#!/usr/bin/env python3
"""Fetch the two public real-telemetry datasets at pinned upstream commits and verify every file.

HAI 22.04 (ETRI, CC BY-SA 4.0): Git LFS objects, verified against the sha256 oid and size in the
LFS pointer committed at the pinned commit. SMD (Su et al., KDD 2019, MIT): plain Git blobs,
verified against the Git blob hash in the pinned tree. Files land in fresh per-dataset folders
under target/real-telemetry/raw and are treated as untrusted data (never executed or imported).
The manifest records upstream identity, size, sha256 and licence for every file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "target" / "real-telemetry" / "raw"
MANIFEST = ROOT / "docs" / "research" / "real_telemetry_data_manifest_v1.json"

HAI = {
    "name": "hai-22.04",
    "repository": "icsdataset/hai",
    "commit": "2a814cebc9a66b06c9e5cd545e2d72e65d383737",
    "folder": "hai-22.04",
    "files": [f"train{i}.csv" for i in range(1, 7)] + [f"test{i}.csv" for i in range(1, 5)],
    "license": "CC BY-SA 4.0 (README licence section and technical manual v4.0; repository has no LICENSE file)",
    "citation": "H.-K. Shin, W. Lee, S. Choi, J.-H. Yun, B.-G. Min. HAI security datasets, https://github.com/icsdataset/hai, 2023; "
                "H.-K. Shin, W. Lee, J.-H. Yun, B.-G. Min. Two ICS Security Datasets and Anomaly Detection Contest on the "
                "HIL-based Augmented ICS Testbed. CSET '21, pp. 36-40. https://doi.org/10.1145/3474718.3474719",
}
SMD = {
    "name": "smd",
    "repository": "NetManAIOps/OmniAnomaly",
    "commit": "7fb0e0acf89ea49908896bcc9f9e80fcfff6baf4",
    "folder": "ServerMachineDataset",
    "license": "MIT (ServerMachineDataset/LICENSE)",
    "citation": "Y. Su, Y. Zhao, C. Niu, R. Liu, W. Sun, D. Pei. Robust Anomaly Detection for Multivariate Time Series "
                "through Stochastic Recurrent Neural Network. KDD 2019, pp. 2828-2837. https://doi.org/10.1145/3292500.3330672",
}


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ferrumos-real-telemetry-fetch"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return response.read()


def download(url: str, destination: Path) -> tuple[int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "ferrumos-real-telemetry-fetch"})
    partial = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(request, timeout=600) as response, partial.open("wb") as handle:
        for block in iter(lambda: response.read(1 << 20), b""):
            handle.write(block)
            digest.update(block)
            size += len(block)
    partial.replace(destination)
    return size, digest.hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


HAI_REPLICATION = {
    "hai-21.03": {"folder": "hai-21.03", "lfs": False,
                  "files": [f"train{i}.csv.gz" for i in range(1, 4)] + [f"test{i}.csv.gz" for i in range(1, 6)]},
    "hai-23.05": {"folder": "hai-23.05", "lfs": True,
                  "files": [f"hai-train{i}.csv" for i in range(1, 5)] + ["hai-test1.csv", "hai-test2.csv",
                                                                        "label-test1.csv", "label-test2.csv"]},
}


def fetch_hai_release(release: str) -> dict:
    """Registered replication releases (rt2): same repository and pinned commit as HAI 22.04."""
    spec = HAI_REPLICATION[release]
    out, records = RAW / release, []
    if spec["lfs"]:
        for name in spec["files"]:
            pointer = get(f"https://raw.githubusercontent.com/{HAI['repository']}/{HAI['commit']}/{spec['folder']}/{name}").decode()
            oid = re.search(r"oid sha256:([0-9a-f]{64})", pointer).group(1)
            expected = int(re.search(r"size (\d+)", pointer).group(1))
            path = out / name
            if not (path.exists() and path.stat().st_size == expected and sha256(path) == oid):
                size, digest = download(f"https://media.githubusercontent.com/media/{HAI['repository']}/{HAI['commit']}/{spec['folder']}/{name}", path)
                assert size == expected and digest == oid, f"{name}: LFS verification failed"
            records.append({"file": name, "bytes": expected, "sha256": oid, "upstream_check": "git-lfs oid sha256 and size"})
            print(f"{release} {name} {expected} ok", flush=True)
    else:
        tree = json.loads(subprocess.run(["gh", "api", f"repos/{HAI['repository']}/git/trees/{HAI['commit']}?recursive=1"],
                                         capture_output=True, text=True, check=True).stdout)
        blobs = {item["path"]: item for item in tree["tree"] if item["type"] == "blob"}
        for name in spec["files"]:
            item = blobs[f"{spec['folder']}/{name}"]
            path = out / name
            if not (path.exists() and path.stat().st_size == item["size"] and git_blob_sha1(path) == item["sha"]):
                download(f"https://raw.githubusercontent.com/{HAI['repository']}/{HAI['commit']}/{item['path']}", path)
                assert path.stat().st_size == item["size"] and git_blob_sha1(path) == item["sha"], f"{name}: blob check failed"
            records.append({"file": name, "bytes": item["size"], "sha256": sha256(path), "git_blob_sha1": item["sha"],
                            "upstream_check": "git blob sha1 at pinned commit"})
            print(f"{release} {name} {item['size']} ok", flush=True)
    return {key: HAI[key] for key in ("repository", "commit", "license", "citation")} | {"files": records}


def fetch_hai() -> dict:
    out, records = RAW / HAI["name"], []
    for name in HAI["files"]:
        pointer = get(f"https://raw.githubusercontent.com/{HAI['repository']}/{HAI['commit']}/{HAI['folder']}/{name}").decode()
        oid = re.search(r"oid sha256:([0-9a-f]{64})", pointer).group(1)
        expected = int(re.search(r"size (\d+)", pointer).group(1))
        path = out / name
        if not (path.exists() and path.stat().st_size == expected and sha256(path) == oid):
            size, digest = download(f"https://media.githubusercontent.com/media/{HAI['repository']}/{HAI['commit']}/{HAI['folder']}/{name}", path)
            assert size == expected and digest == oid, f"{name}: LFS verification failed"
        records.append({"file": name, "bytes": expected, "sha256": oid, "upstream_check": "git-lfs oid sha256 and size"})
        print(f"hai {name} {expected} ok", flush=True)
    return {key: HAI[key] for key in ("repository", "commit", "license", "citation")} | {"files": records}


def fetch_smd() -> dict:
    tree = json.loads(subprocess.run(["gh", "api", f"repos/{SMD['repository']}/git/trees/{SMD['commit']}?recursive=1"],
                                     capture_output=True, text=True, check=True).stdout)
    blobs = [item for item in tree["tree"] if item["type"] == "blob" and item["path"].startswith(SMD["folder"] + "/")]
    out, records = RAW / SMD["name"], []
    for item in sorted(blobs, key=lambda b: b["path"]):
        relative = item["path"][len(SMD["folder"]) + 1:]
        path = out / relative
        if not (path.exists() and path.stat().st_size == item["size"] and git_blob_sha1(path) == item["sha"]):
            download(f"https://raw.githubusercontent.com/{SMD['repository']}/{SMD['commit']}/{item['path']}", path)
            assert path.stat().st_size == item["size"] and git_blob_sha1(path) == item["sha"], f"{relative}: blob check failed"
        records.append({"file": relative, "bytes": item["size"], "sha256": sha256(path), "git_blob_sha1": item["sha"],
                        "upstream_check": "git blob sha1 at pinned commit"})
    print(f"smd {len(records)} files ok", flush=True)
    return {key: SMD[key] for key in ("repository", "commit", "license", "citation")} | {"files": records}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["hai", "smd", "hai-21.03", "hai-23.05"])
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {
        "schema_version": "real-telemetry-data-manifest-v1",
        "policy": "Upstream files are fetched at pinned commits, verified, stored only under target/, and never redistributed here.",
        "datasets": {}}
    if args.only in (None, "hai"):
        manifest["datasets"]["hai-22.04"] = fetch_hai()
    if args.only in (None, "smd"):
        manifest["datasets"]["smd"] = fetch_smd()
    for release in ("hai-21.03", "hai-23.05"):
        if args.only == release:
            manifest["datasets"][release] = fetch_hai_release(release)
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print("manifest", MANIFEST)


if __name__ == "__main__":
    main()
