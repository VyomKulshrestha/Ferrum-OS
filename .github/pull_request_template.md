## What changed and why

<!-- Describe the change. Link a related issue if one exists. -->

## How was this verified?

<!--
This project verifies fixes against a real booted kernel in QEMU, not just
code review or unit tests in isolation - see CONTRIBUTING.md's "Testing"
section. List the scripts/verify_*.mjs runs (new or existing) that confirm
this change, e.g.:

- [ ] scripts/verify_foo.mjs — N/N PASS (new, covers this change)
- [ ] scripts/verify_shell_coexistence.mjs — N/N PASS (regression)
-->

## Docs updated

<!--
Check whatever's applicable - a behavior change without a matching doc
update will likely get asked to add one before merge.
-->

- [ ] `docs/ARCHITECTURE.md` (if this changes something it describes)
- [ ] `README.md` (if this changes a documented command/feature/syscall)
- [ ] Not applicable

## Checklist

- [ ] I ran the relevant `scripts/verify_*.mjs` tests locally
- [ ] I did not silently expand scope beyond what this PR's title describes
