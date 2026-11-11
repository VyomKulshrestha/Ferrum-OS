"""Import closure of the tt1 / tt1b / tt1c entry scripts within scripts/."""
import ast
import sys
from pathlib import Path

SCRIPTS = Path(sys.argv[1])
ENTRY = ["tt1_final.py", "tt1b_final.py", "verify_tt1.py", "verify_tt1b.py", "tt1_paper_pack.py",
         "tt1_memory_check.py", "tt1_posthoc_alarm_time.py", "tt1_posthoc_transient.py", "tt1b_dev.py",
         "tt1b_attacks_dev.py", "tt1b_frog_dev.py", "tt1b_physfrog_dev.py", "tt1b_posthoc.py",
         "tt1b_frog_synthetic.py", "threshold_transfer_dev.py", "tt1c_baselines_dev.py",
         "fetch_real_telemetry.py", "threshold_online.py", "tt1b_dev.py", "tt1e_defense_dev.py",
         "tt1d_final.py", "tt1d_provics_amendment1.py", "verify_tt1d.py",
         "tt1f_tep_dev.py", "tt1f_batadal_trace.py", "tt1f_provics_mask.py", "tt1f_process_dev.py",
         "real_telemetry_detect_v2.py", "threshold_online_v2.py", "threshold_rules_tt1c_v2.py", "tt1d_data_v2.py",
         "test_real_telemetry_detect_v2.py", "test_threshold_online_v2.py", "test_threshold_rules_tt1c_v2.py",
         "test_tt1d_data_v2.py"]
local = {p.stem for p in SCRIPTS.glob("*.py")}
seen, todo = set(), [e for e in ENTRY if (SCRIPTS / e).exists()]
missing = [e for e in ENTRY if not (SCRIPTS / e).exists()]
while todo:
    f = todo.pop()
    if f in seen:
        continue
    seen.add(f)
    tree = ast.parse((SCRIPTS / f).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module.split(".")[0]]
        for n in names:
            if n in local and f"{n}.py" not in seen:
                todo.append(f"{n}.py")
print("missing entries:", missing)
print(len(seen), "files")
for f in sorted(seen):
    print(f, (SCRIPTS / f).stat().st_size)
