#!/usr/bin/env python3
"""Adversarial model of the FerrumOS capability matcher (deterministic authority gate).

This is a host-runnable *model* of the boolean decision logic in
`src/security/mod.rs` (`resource_grant_covers`, used by `has_capability` and
`check_capability`). It is NOT the kernel test: the authoritative behaviour is
the Rust function, verified by the project's build/CI. This script exists so the
gate's authorization decisions can be exercised against an attack corpus and
measured without a kernel build.

Rust `str::starts_with` / `strip_suffix` / `ends_with` / `strip_prefix` map 1:1
to the Python below for ASCII resource strings.

Resource names are segment-structured: ':' separates capability segments and
'/' separates filesystem-path segments; '.' is deliberately NOT a separator
(it appears inside hostnames). A grant must match exactly, at a segment
boundary, or via an explicit trailing '*' wildcard -- never as a bare string
prefix, which would let `fs:read:/pub` authorize `fs:read:/public-secrets`.

Run:  python scripts/authority_matcher_adversarial.py
Exit code 0 iff the delimiter-aware matcher decides every corpus case correctly.
"""
import sys

# (capability-name, resource) exactly as registered in src/security/mod.rs
BUILTINS = [
    ("cap:desktop:configure", "desktop:configure"),
    ("cap:process:spawn", "process:spawn"),
    ("cap:process:kill", "process:kill:*"),
    ("cap:net:listen", "net:listen:*"),
    ("cap:net:connect", "net:connect:*"),
    ("cap:service:register", "service:register"),
    ("cap:audit:read", "audit:read"),
    ("cap:audit:write", "audit:write"),
    ("cap:memory:alloc", "memory:alloc:*"),
    ("cap:ipc:send", "ipc:send:*"),
    ("cap:ipc:receive", "ipc:receive:*"),
    ("cap:agent:control", "agent:*"),
    ("cap:heliox:neural", "heliox:neural:*"),
    ("cap:audio:play", "audio:play"),
    ("cap:audio:record", "audio:record"),
    ("cap:input:inject", "input:inject:*"),
    ("cap:input:read", "input:read:*"),
    ("cap:fs:read", "fs:read:*"),
    ("cap:fs:write", "fs:write:*"),
    ("cap:clipboard:read", "clipboard:read"),
    ("cap:clipboard:write", "clipboard:write"),
]
BOUNDARY = (":", "/")  # '.' is intentionally excluded (hostnames)


def matches_prefix_only(grant, requested):
    """The pre-fix matcher: unbounded string prefix (over-grants at boundaries)."""
    return requested.startswith(grant.rstrip("*"))


def resource_grant_covers(grant, requested):
    """Delimiter-aware matcher, mirroring src/security/mod.rs::resource_grant_covers."""
    if grant.endswith("*"):
        prefix = grant[:-1]
        if not requested.startswith(prefix):
            return False
        rest = requested[len(prefix):]
        return prefix == "" or prefix.endswith(BOUNDARY) or rest == "" or rest.startswith(BOUNDARY)
    return requested == grant or (
        requested.startswith(grant) and requested[len(grant):].startswith(BOUNDARY)
    )


def has_capability(matcher, held, requested):
    if any(h == "cap:system:all" for h in held):
        return True
    return any(matcher(res, requested) for h in held for (name, res) in BUILTINS if name == h)


# (desc, held, requested, should_allow) against the real builtin registry
PHASE1 = [
    ("net:connect holder -> net:connect:*", ["cap:net:connect"], "net:connect:*", True),
    ("net:listen holder -> net:listen:*", ["cap:net:listen"], "net:listen:*", True),
    ("process:spawn holder -> process:spawn", ["cap:process:spawn"], "process:spawn", True),
    ("process:kill holder -> process:kill:*", ["cap:process:kill"], "process:kill:*", True),
    ("audio:play holder -> audio:play", ["cap:audio:play"], "audio:play", True),
    ("fs:read holder -> fs:read:*", ["cap:fs:read"], "fs:read:*", True),
    ("input:read holder -> input:read:*", ["cap:input:read"], "input:read:*", True),
    ("no caps -> net:connect:*", [], "net:connect:*", False),
    ("audio:play holder -> audio:record (sibling)", ["cap:audio:play"], "audio:record", False),
    ("net:connect holder -> net:listen:* (sibling)", ["cap:net:connect"], "net:listen:*", False),
    ("process:spawn holder -> process:kill:* (sibling)", ["cap:process:spawn"], "process:kill:*", False),
    ("fs:read holder -> fs:write:* (sibling)", ["cap:fs:read"], "fs:write:*", False),
    ("clipboard:read holder -> clipboard:write", ["cap:clipboard:read"], "clipboard:write", False),
]
# Scoped/hierarchical resources: the latent boundary defect, live as soon as a
# capability is scoped to a host or path (anticipated by pkg/mod.rs + fs comments).
# (desc, grant_resource, requested, should_allow)
PHASE2 = [
    ("grant net:connect:api.internal -> api.internal:443", "net:connect:api.internal", "net:connect:api.internal:443", True),
    ("grant net:connect:api.internal -> api.internal (exact)", "net:connect:api.internal", "net:connect:api.internal", True),
    ("OVER-MATCH net:connect:api.internal -> api.internal.evil.com", "net:connect:api.internal", "net:connect:api.internal.evil.com", False),
    ("OVER-MATCH fs:read:/pub -> /public-secrets", "fs:read:/pub", "fs:read:/public-secrets", False),
    ("grant fs:read:/pub/* -> /pub/report (wildcard)", "fs:read:/pub/*", "fs:read:/pub/report", True),
    ("grant fs:read:/pub -> /pub/report (child seg)", "fs:read:/pub", "fs:read:/pub/report", True),
]


def main():
    cur = fix = 0
    print("== Phase 1: real builtin capabilities ==")
    for desc, held, req, want in PHASE1:
        c = has_capability(matches_prefix_only, held, req)
        f = has_capability(resource_grant_covers, held, req)
        cur += c == want
        fix += f == want
        print(f"  want={str(want):<5} prefix={str(c):<5} fixed={str(f):<5} | {desc}"
              + ("  <-- differs" if c != f else ""))
    print(f"  prefix-only: {cur}/{len(PHASE1)}   delimiter-aware: {fix}/{len(PHASE1)}")

    scur = sfix = 0
    print("\n== Phase 2: scoped/hierarchical resources (latent boundary defect) ==")
    for desc, grant, req, want in PHASE2:
        c = matches_prefix_only(grant, req)
        f = resource_grant_covers(grant, req)
        scur += c == want
        sfix += f == want
        print(f"  want={str(want):<5} prefix={str(c):<5} fixed={str(f):<5} | {desc}"
              + ("  <-- differs" if c != f else ""))
    print(f"  prefix-only: {scur}/{len(PHASE2)}   delimiter-aware: {sfix}/{len(PHASE2)}")

    tot = len(PHASE1) + len(PHASE2)
    over = sum(1 for _, g, r, w in PHASE2 if matches_prefix_only(g, r) and not w)
    print("\n== SUMMARY (decisions correct vs authorization intent) ==")
    print(f"  prefix-only matcher:     {cur + scur}/{tot}  (over-grants {over} boundary case(s))")
    print(f"  delimiter-aware matcher: {fix + sfix}/{tot}")
    return 0 if (fix + sfix) == tot else 1


if __name__ == "__main__":
    sys.exit(main())
