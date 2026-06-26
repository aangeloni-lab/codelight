#!/usr/bin/env python3
"""
codelight_gui.py – minimal cross-platform tray-style window for claude_monitor.

Lets a non-technical user enter the device hostname/secret, start/stop the
monitor loop, and optionally enable "start at login" — without touching a
terminal. Runs the existing claude_monitor logic in a background thread.
"""
import json
import os
import platform
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_monitor as cm

APP_NAME = "Codelight"


def config_dir() -> str:
    system = platform.system()
    if system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def load_config() -> dict:
    try:
        with open(config_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    os.makedirs(config_dir(), exist_ok=True)
    with open(config_path(), "w") as f:
        json.dump(cfg, f, indent=2)


# ── Autostart at login ───────────────────────────────────────────────────────

def _macos_launch_agent_path() -> str:
    return os.path.expanduser(
        "~/Library/LaunchAgents/com.codelight.monitor.plist")


def set_autostart_macos(enabled: bool, script_path: str) -> None:
    plist_path = _macos_launch_agent_path()
    if not enabled:
        if os.path.exists(plist_path):
            os.system(f"launchctl unload '{plist_path}' 2>/dev/null")
            os.remove(plist_path)
        return

    python_exe = sys.executable
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.codelight.monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe}</string>
        <string>{script_path}</string>
        <string>--autostart</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""
    os.makedirs(os.path.dirname(plist_path), exist_ok=True)
    with open(plist_path, "w") as f:
        f.write(plist)
    os.system(f"launchctl unload '{plist_path}' 2>/dev/null")
    os.system(f"launchctl load '{plist_path}' 2>/dev/null")


def set_autostart_windows(enabled: bool, script_path: str) -> None:
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                         winreg.KEY_SET_VALUE) as key:
        if enabled:
            cmd = f'"{sys.executable}" "{script_path}" --autostart'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def set_autostart(enabled: bool) -> None:
    script_path = os.path.abspath(__file__)
    system = platform.system()
    if system == "Darwin":
        set_autostart_macos(enabled, script_path)
    elif system == "Windows":
        set_autostart_windows(enabled, script_path)
    # Other platforms: no-op (autostart checkbox has no effect there).


class CodelightApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.stop_event = threading.Event()
        self.thread = None

        cfg = load_config()

        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(root)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frm, text="Device hostname or IP").grid(row=0, column=0, sticky="w", **pad)
        self.device_var = tk.StringVar(value=cfg.get("device", "claude-screen.local"))
        ttk.Entry(frm, textvariable=self.device_var, width=30).grid(row=0, column=1, **pad)

        ttk.Label(frm, text="Secret (optional)").grid(row=1, column=0, sticky="w", **pad)
        self.secret_var = tk.StringVar(value=cfg.get("secret", ""))
        ttk.Entry(frm, textvariable=self.secret_var, width=30, show="•").grid(row=1, column=1, **pad)

        self.autostart_var = tk.BooleanVar(value=cfg.get("autostart", False))
        ttk.Checkbutton(frm, text="Start automatically at login",
                         variable=self.autostart_var,
                         command=self._on_autostart_toggle).grid(
            row=2, column=0, columnspan=2, sticky="w", **pad)

        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(frm, textvariable=self.status_var, foreground="#888").grid(
            row=3, column=0, columnspan=2, sticky="w", **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, pady=(8, 0))
        self.start_btn = ttk.Button(btns, text="Start", command=self.start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(btns, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if cfg.get("autostart") and platform.system() in ("Darwin", "Windows"):
            set_autostart(True)  # idempotent, re-applies in case script path moved

        if "--autostart" in sys.argv:
            self.root.after(100, self.start)
            self.root.iconify()

    def _on_autostart_toggle(self):
        set_autostart(self.autostart_var.get())
        self._save()

    def _save(self):
        save_config({
            "device": self.device_var.get().strip(),
            "secret": self.secret_var.get(),
            "autostart": self.autostart_var.get(),
        })

    def start(self):
        device = self.device_var.get().strip()
        if not device:
            messagebox.showerror(APP_NAME, "Enter the device hostname or IP first.")
            return
        self._save()

        url = f"http://{device}/status"
        headers = {"Content-Type": "application/json"}
        secret = self.secret_var.get()
        if secret:
            headers["X-Secret"] = secret

        self.stop_event.clear()

        def on_update(payload, result, error):
            if error is not None:
                text = f"Offline: {error}"
            elif result is not None and result.status_code == 200:
                text = (f"{payload['status'].upper()} · "
                        f"{payload['sessions']} session(s) · "
                        f"{payload['tokens_in'] + payload['tokens_out']:,} tokens")
            else:
                code = result.status_code if result is not None else "?"
                text = f"Device returned HTTP {code}"
            self.root.after(0, lambda: self.status_var.set(text))

        def run():
            try:
                cm.install_hooks(os.path.abspath(cm.__file__))
                cm.run_monitor_loop(url, headers, on_update=on_update,
                                     stop_event=self.stop_event)
            except Exception as e:
                self.root.after(0, lambda: self._on_thread_error(str(e)))

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Starting…")

    def _on_thread_error(self, message: str):
        self.status_var.set(f"Error: {message}")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def stop(self):
        self.stop_event.set()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Stopped")

    def _on_close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    CodelightApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
