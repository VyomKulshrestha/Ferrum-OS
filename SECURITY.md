# Security Policy

## Scope

FerrumOS is a bare-metal, hobby/research operating system: a kernel plus a
set of freestanding userland processes, including an AI agent runtime
(`heliox-daemon`) with capability-gated access to hardware and the
filesystem. Security issues in scope include (non-exhaustively):

- Privilege escalation across the ring-0/ring-3 boundary (e.g. a ring-3
  process reaching kernel memory or executing arbitrary ring-0 code)
- Capability/security model bypasses (a process performing an action its
  granted capabilities shouldn't allow — see `src/security/`)
- Confirmation-gate bypasses for Tier-3/Tier-4 agent actions (e.g.
  `DeleteFile`, `Kexec` executing without operator confirmation — see
  `docs/ARCHITECTURE.md`'s Permission Tiers)
- Memory-safety issues in the kernel's `unsafe` code (paging, context
  switching, the ext2 driver, syscall argument handling from userspace)
- Anything that lets an agent-issued tool call bypass its intended
  sandboxing (`heliox-daemon`'s `ConfirmationGate`/world-model safety gate)

This is not a production OS handling real user data or running on real
hardware in a security-sensitive deployment today — please calibrate
severity accordingly, but we'd still like to know about anything real.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for a security vulnerability.**

Instead, please report it privately using
[GitHub's private vulnerability reporting](https://github.com/VyomKulshrestha/Ferrum-OS/security/advisories/new)
for this repository (Security tab → "Report a vulnerability"). If that's
unavailable to you, open a regular issue asking for a private contact
channel without describing the vulnerability itself, and we'll follow up.

Please include:
- A description of the issue and its potential impact
- Steps to reproduce (ideally against a real boot in QEMU — see
  [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to build and boot)
- Any relevant `src/` file:line references if you've already narrowed it
  down

## What to expect

This is currently a small/single-maintainer project, so response times
won't match a funded security team's SLA — but we'll acknowledge reports
as soon as we see them and keep you updated as we investigate and fix.

## Disclosure

We ask that you give us a reasonable amount of time to address a reported
issue before any public disclosure. We'll credit reporters (unless you'd
prefer otherwise) once a fix ships.
