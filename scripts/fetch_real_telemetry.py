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
    """Download with resume: an existing .part file is continued with an HTTP Range request."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(8):
        have = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "ferrumos-real-telemetry-fetch"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
                mode = "ab" if have and response.status == 206 else "wb"
                with partial.open(mode) as handle:
                    for block in iter(lambda: response.read(1 << 20), b""):
                        handle.write(block)
            break
        except (TimeoutError, OSError) as error:
            print(f"download interrupted at {partial.stat().st_size if partial.exists() else 0} bytes ({error}); resuming", flush=True)
    partial.replace(destination)
    return destination.stat().st_size, sha256(destination)


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
    "hai-20.07": {"folder": "hai-20.07", "lfs": False,
                  "files": ["train1.csv.gz", "train2.csv.gz", "test1.csv.gz", "test2.csv.gz"]},
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


# Threshold-transfer study (tt1) fresh sources: published files verified by publisher checksum or size.
EXTERNAL = {
    "hygrid-ics": {
        "record": "https://doi.org/10.5281/zenodo.23250890 (HyGrid-ICS v1.1.1)",
        "license": "CC BY 4.0",
        "citation": "HyGrid-ICS: A Hybrid Cyber-Physical Security Dataset for SCADA-Based Industrial Control Systems, v1.1.1, Zenodo, 2026. https://doi.org/10.5281/zenodo.23250890",
        "files": {
            "scada_cps_dataset.csv": ("https://zenodo.org/api/records/23250890/files/scada_cps_dataset.csv/content", 96522760, "md5", "385153824abe5253646ff79402007416"),
            "attack_labels.csv": ("https://zenodo.org/api/records/23250890/files/attack_labels.csv/content", 6783, "md5", "5fd0a810a5b49122b6b6b24c43b7d926"),
            "HyGrid-ICS-v1.0.0.zip": ("https://zenodo.org/api/records/23250890/files/HyGrid-ICS-v1.0.0.zip/content", 97015, "md5", "965eafa032e5e2e12e76fa5cc11569e6"),
        },
    },
    "voraus-ad": {
        "record": "https://github.com/vorausrobotik/voraus-ad-dataset (100 Hz release)",
        "license": "CC BY-NC-SA 4.0 (data), MIT (code)",
        "citation": "J. Brockmann, M. Rudolph, B. Rosenhahn, B. Wandt. The voraus-AD Dataset for Anomaly Detection in Robot Applications. IEEE Transactions on Robotics, 2024. arXiv:2311.04765",
        "files": {
            "voraus-ad-dataset-100hz.parquet": ("https://media.vorausrobotik.com/voraus-ad-dataset-100hz.parquet", 1115942833, "etag", "69d8ea42-4283efb1"),
        },
    },
}


def fetch_external(name: str) -> dict:
    spec = EXTERNAL[name]
    out, records = RAW / name, []
    for fname, (url, size, kind, expected) in spec["files"].items():
        path = out / fname
        if not (path.exists() and path.stat().st_size == size):
            got, digest = download(url, path)
            assert got == size, f"{fname}: size {got} != {size}"
        sha = sha256(path)
        if kind == "md5":
            md5 = hashlib.md5(path.read_bytes()).hexdigest()
            assert md5 == expected, f"{fname}: md5 mismatch"
        records.append({"file": fname, "bytes": size, "sha256": sha, "upstream_check": f"{kind} {expected} and size"})
        print(f"{name} {fname} {size} ok", flush=True)
    return {key: spec[key] for key in ("record", "license", "citation")} | {"files": records}


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
    parser.add_argument("--only", choices=["hai", "smd", "hai-20.07", "hai-21.03", "hai-23.05", "hygrid-ics", "voraus-ad"])
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {
        "schema_version": "real-telemetry-data-manifest-v1",
        "policy": "Upstream files are fetched at pinned commits, verified, stored only under target/, and never redistributed here.",
        "datasets": {}}
    if args.only in (None, "hai"):
        manifest["datasets"]["hai-22.04"] = fetch_hai()
    if args.only in (None, "smd"):
        manifest["datasets"]["smd"] = fetch_smd()
    for release in ("hai-20.07", "hai-21.03", "hai-23.05"):
        if args.only == release:
            manifest["datasets"][release] = fetch_hai_release(release)
    for name in ("hygrid-ics", "voraus-ad"):
        if args.only == name:
            manifest["datasets"][name] = fetch_external(name)
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print("manifest", MANIFEST)


if __name__ == "__main__":
    main()
