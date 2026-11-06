"""Minimal docstrip for acmart.dtx (option "class", \\keepsilent): keeps the code lines whose guards are true.
Guard grammar handled: names, !, &, | and parentheses, block guards %<*expr> ... %</expr>, line guards %<expr>."""
import re
import sys
from pathlib import Path

OPTIONS = {"class"}


def true(expr):
    py = re.sub(r"[A-Za-z_][A-Za-z0-9_-]*", lambda m: str(m.group(0) in OPTIONS), expr)
    py = py.replace("!", " not ").replace("&", " and ").replace("|", " or ")
    return bool(eval(py))


src = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
stack, out, outside = [], [], 0
for line in src:
    if line.startswith("%<*"):
        stack.append(line[3:line.index(">")])
        continue
    if line.startswith("%</"):
        stack.pop()
        continue
    if line.startswith("%<"):
        expr, rest = line[2:line.index(">")], line[line.index(">") + 1:]
        if true(expr) and all(true(s) for s in stack):
            out.append(rest)
        continue
    if line.startswith("%"):
        continue
    if not stack:                     # docstrip copies unguarded code lines into every generated file
        outside += 1
        out.append(line)
        continue
    if all(true(s) for s in stack):
        out.append(line)
Path(sys.argv[2]).write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
print(len(out), "lines written;", outside, "unguarded code lines kept")
