"""Build the anonymized review artifact for "Thresholds That Travel" from the repository.

    python scripts/tt1_build_artifact.py <artifact folder>

Copies the scripts in the import closure of the study's entry points (scripts/tt1_artifact_deps.py), the
registrations, data-access logs, results, verifier reports, the access ledger and the figure data/code,
plus docs/research/paper/artifact/ (README, requirements, .gitignore); replaces identifying strings; writes
ANONYMIZATION.md listing every replacement; then scans the output and refuses to finish if an identifying
string remains. The artifact folder is rebuilt in place; its own .git is kept.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
DST = Path(sys.argv[1])
SCRIPTS = subprocess.run([sys.executable, "-B", str(SRC / "scripts/tt1_artifact_deps.py"), str(SRC / "scripts")],
                         capture_output=True, text=True, check=True).stdout.splitlines()[2:]
SCRIPTS = [line.split()[0] for line in SCRIPTS if line.strip()]

DOC_PATTERNS = [r"^threshold_transfer_.*\.(json|md)$", r"^monitor_audit_.*\.md$", r"^real_telemetry_detection_protocol_v2.*\.json$",
                r"^real_telemetry_detection_v2_result_(hai-20\.07|hygrid-ics)\.json$",
                r"^real_telemetry_protocol_(v1|rt2)(_amendment\d)?\.json$",
                r"^fi1_monitor_round[12]\.json$"]  # cited by the post-hoc paragraph on the fitted range (Section 5.2)
# Reports in subfolders of docs/research that the paper cites (the fitted-range definition is in round 2).
DOC_SUBFILES = ["fi1_reports/monitor_round1.md", "fi1_reports/monitor_round2.md"]
PACK = SRC / "docs/research/paper/tt1_paper_pack"
PACK_DIRS = ["figure_data", "figures"]

own = set(subprocess.run(["git", "-C", str(SRC), "log", "--all", "--format=%H"], capture_output=True,
                         text=True, check=True).stdout.split())
TEXT_RE = [  # (pattern, replacement, reason)
    (re.compile(r"ferrumos-real-telemetry-fetch"), "real-telemetry-fetch", "project name in an HTTP User-Agent"),
    (re.compile(r"FerrumOS"), "[project]", "project name"),
    (re.compile(r"(?i)ferrum[- ]?os"), "[project]", "project name"),
]
HEX = re.compile(r"\b[0-9a-f]{7,40}\b")


def own_sha(tok):
    return re.search(r"[a-f]", tok) and re.search(r"\d", tok) and any(h.startswith(tok) for h in own)


def anonymize(text):
    notes = []
    for pat, rep, why in TEXT_RE:
        n = len(pat.findall(text))
        if n:
            text = pat.sub(rep, text)
            notes.append(f"{n} x {why} -> `{rep}`")
    k = 0

    def sub(m):
        nonlocal k
        if own_sha(m.group(0)):
            k += 1
            return "[commit]"
        return m.group(0)

    text = HEX.sub(sub, text)
    if k:
        notes.append(f"{k} x commit hash of the authors' repository -> `[commit]`")
    return text, notes


def lf_sha(b):
    return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()


if DST.exists():
    for child in DST.iterdir():                      # rebuild in place, keeping the artifact's own git history
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
files = [(SRC / "scripts" / f, Path("scripts") / f) for f in SCRIPTS]
for f in sorted((SRC / "docs/research").iterdir()):
    if any(re.match(p, f.name) for p in DOC_PATTERNS):
        files.append((f, Path("docs/research") / f.name))
for name in DOC_SUBFILES:
    files.append((SRC / "docs/research" / name, Path("docs/research") / name))
for d in PACK_DIRS:
    for f in sorted((PACK / d).rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            files.append((f, Path("docs/research/paper") / d / f.relative_to(PACK / d)))
files.append((SRC / "target/real-telemetry/final_access.jsonl", Path("target/real-telemetry/final_access.jsonl")))

log = []
for src, rel in files:
    out = DST / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = src.read_bytes()
    if src.suffix in (".py", ".json", ".md", ".csv", ".jsonl", ".txt", ".svg"):
        text, notes = anonymize(raw.decode("utf-8"))
        out.write_text(text, encoding="utf-8", newline="\n")
        if notes:
            log.append((str(rel).replace("\\", "/"), lf_sha(raw), lf_sha(text.encode("utf-8")), notes))
    else:
        out.write_bytes(raw)

# final scan: nothing identifying may remain
BAD = re.compile(r"(?i)vyom|kulshrestha|hardik|ferrum|dovel|heliox|cursor-os|marcu|C:[\\/]+Users|@gmail|0009-0009-1434|"
                 r"2346936[23]|2347318[35]|2209232\d|2209235\d|github\.com/VyomK")
problems = []
for f in DST.rglob("*"):
    if f.is_file() and f.suffix in (".py", ".json", ".md", ".csv", ".jsonl", ".txt", ".svg"):
        t = f.read_text(encoding="utf-8", errors="replace")
        for m in BAD.finditer(t):
            problems.append((str(f.relative_to(DST)), t[max(0, m.start() - 30):m.end() + 30]))
        for m in HEX.finditer(t):
            if own_sha(m.group(0)):
                problems.append((str(f.relative_to(DST)), m.group(0)))
if problems:
    for p in problems[:30]:
        print("IDENTIFYING:", p)
    raise SystemExit(f"{len(problems)} identifying strings remain")
EXTRA = SRC / "docs/research/paper/artifact"
for f in EXTRA.iterdir():
    shutil.copyfile(f, DST / (".gitignore" if f.name == "gitignore.txt" else f.name))
frozen = set(json.loads((SRC / "docs/research/threshold_transfer_tt1_protocol.json").read_text(encoding="utf-8"))
             .get("frozen_file_sha256", {}))
lines = ["# Anonymization record", "",
         "This copy differs from the authors' repository only in the strings below, replaced for double-blind",
         "review. Comments, docstrings, notes and identifiers in result files were changed; no executable",
         "statement was. SHA-256 values are of the file with LF line endings: the first is the original (for",
         "registered frozen files it equals the digest stored in the protocol and the result files), the second",
         "is this copy.", "",
         "| File | Replaced | Frozen at registration | SHA-256 original | SHA-256 here |", "|---|---|---|---|---|"]
for rel, a, b, notes in log:
    lines.append(f"| `{rel}` | {'; '.join(notes)} | {'yes' if rel in frozen else 'no'} | `{a[:16]}...` | `{b[:16]}...` |")
lines += ["", "Because two frozen files differ, `scripts/tt1_final.py` refuses a final run on this copy and the",
          "verifiers report their digests as changed. The git history, which the verifiers use to check that",
          "every data access came after its registration commit, is withheld until the camera-ready version."]
(DST / "ANONYMIZATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(len(files), "files copied;", len(log), "files anonymized; scan clean")
for rel, a, b, notes in log:
    print(" ", rel, notes)
