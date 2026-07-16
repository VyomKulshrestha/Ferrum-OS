---
name: Bug report
about: Something in the kernel, a userland app, or the shell doesn't behave correctly
title: ''
labels: bug
assignees: ''
---

## Describe the bug

A clear, concise description of what's wrong.

## Reproduction

Exact steps to reproduce, ideally as shell commands typed at the
`FerrumOS:~$` prompt (or a `scripts/verify_*.mjs` invocation, if you have
one):

```
1. .\build.ps1 build
2. .\build.ps1 run-appliance
3. type: ...
4. observe: ...
```

## Expected behavior

What you expected to happen instead.

## Serial log / output

Paste the relevant serial console output (or attach the full log). If the
kernel panicked, include the full panic message.

```
paste here
```

## Environment

- OS/host: (e.g. Windows 11)
- QEMU version: (`qemu-system-x86_64 --version`)
- Commit/branch: (`git rev-parse HEAD`)

## Additional context

Anything else relevant — did this used to work before a recent change?
