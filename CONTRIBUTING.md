# Contributing to FerrumOS

Thanks for your interest in contributing! This guide covers the repo layout,
how to get a dev environment running, and what to check before opening a
pull request.

## Repository layout

FerrumOS is a Rust workspace: a bare-metal x86_64 kernel plus a set of
freestanding userland processes it loads and runs in ring 3.

```
src/            — the kernel: bootloader integration, GDT/IDT/interrupts,
                  paging & heap, scheduler, VFS + ext2 driver, syscall ABI,
                  GUI compositor/desktop, shell + built-in commands,
                  capability-based security, device drivers
userland/       — freestanding ring-3 processes, loaded via the kernel's
                  ELF loader (each one is its own crate):
  init/                    — supervises heliox-daemon, first process launched
  heliox-daemon/           — the AI agent runtime (ReAct loop, world model,
                              tool_mapper, confirmation gate)
  heliox-bridge/           — shared IPC/JSON-RPC types between the daemon
                              and the kernel
  heliox-assistant-panel/  — the agent chat window + first-run setup wizard
  libferrumgui/            — shared SDK every GUI app links against
                              (window creation, canvas, input polling)
  text-editor/, calculator/, file-manager/, settings/, browser/,
  app-store/, notes/       — installed apps built on libferrumgui
  gui-smoke-test/          — minimal app used by scripts/verify_app_window.mjs
scripts/        — verify_*.mjs: boots the real kernel in QEMU, drives the
                  shell/GUI via the QEMU monitor (keyboard/mouse injection),
                  and asserts on the serial log - see "Testing" below
docs/           — architecture reference (docs/ARCHITECTURE.md)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how the kernel's
subsystems fit together, and the root [`README.md`](README.md) for the
feature tour, shell command reference, and syscall table.

## Dev environment setup

### Prerequisites

- **Rust nightly** (this project pins a specific nightly via
  [`rust-toolchain.toml`](rust-toolchain.toml) — `rustup` will fetch it
  automatically the first time you build)
- **QEMU** (`qemu-system-x86_64`) to actually boot and run the kernel
- **Node.js** to run the `scripts/verify_*.mjs` test suite
- Windows + PowerShell is the primary supported dev environment today
  (`build.ps1` drives the whole build/run/test loop) — the kernel itself
  targets bare-metal `x86_64-unknown-none` and isn't Windows-specific, but
  the tooling around it currently is

### 1. Clone the repo

```powershell
git clone https://github.com/VyomKulshrestha/Ferrum-OS.git
cd Ferrum-OS
```

### 2. Generate the mock model fixtures

`userland/init` embeds a small mock model + tokenizer via `include_bytes!`
(`userland/init/fixtures/*.bin`) — these are build inputs, not checked
into git, and must exist before the first build:

```powershell
node scripts/generate_mock_model.mjs
```

### 3. Build the kernel + userland + bootimage

```powershell
.\build.ps1 build
```

### 4. Boot it

```powershell
.\build.ps1 run          # plain kernel image
.\build.ps1 run-appliance  # boots with the packaged appliance disk (real model, packages)
```

`run-appliance` needs `target\heliox-disk.img`, staged by
[`scripts/make-appliance.ps1`](scripts/make-appliance.ps1).

### 5. Run the test suite

```powershell
node scripts/verify_shell_coexistence.mjs
node scripts/verify_pkg_manager.mjs
# ... see scripts/ for the full list, one verify_*.mjs per feature/fix
```

Each `verify_*.mjs` boots a real QEMU instance headless, drives the shell
or GUI through the QEMU monitor (synthetic keyboard/mouse events — no
mocking of kernel behavior), and asserts on the serial console log. They're
independent scripts, not a single test runner — run the ones relevant to
what you touched, plus a broader regression pass (shell/scheduler/GUI
changes especially tend to have non-obvious cross-cutting effects) before
opening a PR.

## Code style

- **Comments**: default to *no* comments. Only add one when the *why* is
  genuinely non-obvious — a hidden constraint, a subtle invariant, a
  workaround for a specific bug. Well-named identifiers should carry the
  *what*; comments are for the *why* a future reader can't otherwise see.
- **Scope discipline**: a bug fix doesn't need surrounding cleanup; a
  one-shot change doesn't need a new abstraction "for later." Prefer the
  narrowest change that honestly solves the problem in front of it.
- **No speculative error handling**: don't add fallbacks or validation for
  scenarios that can't happen given the kernel's own invariants. Validate
  at real boundaries (syscall arguments from userspace, disk I/O), not
  everywhere.
- **Verify against the real thing**: this project has a strong bias toward
  proving a fix against the actual booted kernel in QEMU (see "Testing"
  above) over reasoning from source alone — several real bugs in this
  codebase were only found by actually booting and driving the shell, not
  by code review.

## Submitting a pull request

1. **Fork** the repository and create a feature branch.
2. **Make your change**, and run the relevant `scripts/verify_*.mjs` tests
   before opening the PR — plus a broader regression pass, since
   scheduler/GUI/shell changes especially tend to have non-obvious
   cross-cutting effects.
3. **Add a new `scripts/verify_*.mjs`** for new behavior or a bug fix,
   following the pattern of an existing one close to what you touched (they
   all follow the same shape: boot QEMU headless, drive input via the
   monitor, `waitForSerial`/assert on the log, report `N/M checks passed`).
4. **Update docs alongside code, not after** — `docs/ARCHITECTURE.md`/
   `README.md` if you touched something they describe. A PR that changes
   behavior without updating the docs describing that behavior will likely
   get asked to do so before merge.
5. **Open the PR** against `main` with a clear description of what changed
   and why, and what you verified.

## Reporting bugs / requesting features

Please use the issue templates:
- [Bug report](.github/ISSUE_TEMPLATE/bug_report.md)
- [Feature request](.github/ISSUE_TEMPLATE/feature_request.md)

## Security issues

Please **do not** open a public issue for a security vulnerability — see
[SECURITY.md](SECURITY.md) for how to report one responsibly.

## License

By contributing, you agree that your contributions will be licensed under
this repository's [MIT License](LICENSE).
