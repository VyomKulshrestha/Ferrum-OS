#!/usr/bin/env python3
"""Visible local keyboard controller for Computer Use -> QEMU HMP key events."""

from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import time
import tkinter as tk
from pathlib import Path


KEY_NAMES = {
    " ": "spc",
    ".": "dot",
    ",": "comma",
    "/": "slash",
    "-": "minus",
    "_": "shift-minus",
    ":": "shift-semicolon",
    "'": "apostrophe",
    "?": "shift-slash",
}

# Keep each emulated PS/2 key down long enough for a saturated guest to
# service the interrupt.  The earlier 20 ms pulse worked during boot but was
# observably lost once the local model had paged in and the guest stayed at
# full CPU; spacing commands alone cannot recover an overwritten scancode.
KEY_HOLD_MS = 180


def hmp_key(character: str) -> str:
    if character.isascii() and character.isalpha():
        return f"shift-{character.lower()}" if character.isupper() else character
    if character.isdigit():
        return character
    if character in KEY_NAMES:
        return KEY_NAMES[character]
    raise ValueError(f"unsupported character: {character!r}")


def send_text(port: int, text: str) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as monitor:
        monitor.settimeout(0.2)
        try:
            monitor.recv(4096)
        except TimeoutError:
            pass
        for character in text:
            monitor.sendall(
                f"sendkey {hmp_key(character)} {KEY_HOLD_MS}\n".encode("ascii")
            )
            time.sleep(0.80)
        time.sleep(0.25)
        monitor.sendall(f"sendkey ret {KEY_HOLD_MS}\n".encode("ascii"))
        time.sleep(0.25)


def send_enter(port: int) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as monitor:
        monitor.settimeout(0.2)
        try:
            monitor.recv(4096)
        except TimeoutError:
            pass
        monitor.sendall(f"sendkey ret {KEY_HOLD_MS}\n".encode("ascii"))
        time.sleep(0.25)


def send_alt_tab(port: int) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as monitor:
        monitor.settimeout(0.2)
        try:
            monitor.recv(4096)
        except TimeoutError:
            pass
        monitor.sendall(b"sendkey alt-tab 500\n")
        time.sleep(0.75)


def claim_desktop_input(port: int) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as monitor:
        monitor.settimeout(0.2)
        try:
            monitor.recv(4096)
        except TimeoutError:
            pass
        # QEMU's legacy mouse is relative.  Clamp at the guest origin, then
        # move to a point inside the first-run Heliox app that is outside the
        # overlapping System Monitor and Terminal windows.  Clicking at the
        # prior cursor position made focus depend on incidental pointer state.
        for _ in range(12):
            monitor.sendall(b"mouse_move -100 -100\n")
            time.sleep(0.05)
        # Keep deltas within one PS/2 packet.  A single 420x500 legacy move
        # is truncated by the emulated device and lands near the origin.
        for _ in range(4):
            monitor.sendall(b"mouse_move 100 100\n")
            time.sleep(0.10)
        monitor.sendall(b"mouse_move 20 100\n")
        time.sleep(0.20)
        monitor.sendall(b"mouse_button 1\n")
        time.sleep(0.25)
        monitor.sendall(b"mouse_button 0\n")
        time.sleep(0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    runtime["controller_pid"] = os.getpid()
    args.runtime.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    prompts = json.loads(
        (root / "docs/research/world_model_natural_use_prompts_v1.json").read_text(encoding="utf-8")
    )
    registered = next(item for item in prompts["sessions"] if item["session"] == runtime["session"])["prompts"]

    window = tk.Tk()
    window.title(f"Ferrum Natural Use Controller {runtime['session']}")
    window.geometry("760x640")
    tk.Label(
        window,
        text="Computer Use input -> local QEMU hardware key events (no JSON-RPC execution)",
        font=("Segoe UI", 11, "bold"),
    ).pack(padx=16, pady=(16, 8), anchor="w")
    prompt_list = tk.Listbox(window, height=10, font=("Segoe UI", 10))
    for index, prompt in enumerate(registered, 1):
        prompt_list.insert(tk.END, f"{index}. {prompt}")
    prompt_list.pack(fill="x", padx=16, pady=8)
    tk.Label(window, text="Type exactly one registered line below:", font=("Segoe UI", 10)).pack(padx=16, anchor="w")
    editor = tk.Text(window, height=5, wrap="word", font=("Segoe UI", 12))
    editor.pack(fill="x", padx=16, pady=8)
    status = tk.StringVar(value="Ready")

    def send() -> None:
        text = editor.get("1.0", "end").strip()
        if not text:
            status.set("Nothing sent: input is empty")
            return
        status.set("Sending hardware key events...")
        button.config(state="disabled")

        def worker() -> None:
            try:
                send_text(int(runtime["monitor_port"]), text)
                message = "Sent to visible FerrumOS guest"
            except Exception as error:  # displayed locally; no prompt content logged
                message = f"Send failed: {error}"
            window.after(0, lambda: finish(message))

        threading.Thread(target=worker, daemon=True).start()

    def finish(message: str) -> None:
        status.set(message)
        editor.delete("1.0", "end")
        button.config(state="normal")
        editor.focus_set()

    def claim() -> None:
        status.set("Claiming guest desktop input...")

        def worker() -> None:
            try:
                claim_desktop_input(int(runtime["monitor_port"]))
                message = "Guest desktop input claimed"
            except Exception as error:
                message = f"Desktop claim failed: {error}"
            window.after(0, lambda: status.set(message))

        threading.Thread(target=worker, daemon=True).start()

    button = tk.Button(window, text="Send to FerrumOS", command=send, font=("Segoe UI", 11))
    button.pack(padx=16, pady=8, anchor="w")
    enter_button = tk.Button(
        window,
        text="Press Enter only",
        command=lambda: threading.Thread(
            target=send_enter, args=(int(runtime["monitor_port"]),), daemon=True
        ).start(),
        font=("Segoe UI", 10),
    )
    enter_button.pack(padx=16, pady=4, anchor="w")
    switch_button = tk.Button(
        window,
        text="Switch guest window (Alt+Tab)",
        command=lambda: threading.Thread(
            target=send_alt_tab, args=(int(runtime["monitor_port"]),), daemon=True
        ).start(),
        font=("Segoe UI", 10),
    )
    switch_button.pack(padx=16, pady=4, anchor="w")
    claim_button = tk.Button(
        window,
        text="Claim guest desktop input (click)",
        command=claim,
        font=("Segoe UI", 10),
    )
    claim_button.pack(padx=16, pady=4, anchor="w")
    tk.Label(window, textvariable=status, font=("Segoe UI", 10)).pack(padx=16, pady=8, anchor="w")
    editor.focus_set()
    window.mainloop()


if __name__ == "__main__":
    main()
