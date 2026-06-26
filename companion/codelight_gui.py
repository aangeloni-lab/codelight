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
import time
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_monitor as cm

APP_NAME = "Codelight"

# ── Colours (mirror src/display.cpp) ─────────────────────────────────────────
COL_BG     = "#000000"
COL_TITLE  = "#FFFFFF"
COL_LABEL  = "#C6C6C6"
COL_BAR_BG = "#212121"
COL_RESET  = "#848484"
COL_GREEN  = "#00C800"
COL_ORANGE = "#FF8C00"
COL_RED    = "#FF2200"
COL_OFFLINE = "#404040"


def _lerp(c0, c1, t):
    return tuple(int(round(a + t * (b - a))) for a, b in zip(c0, c1))


def _usage_color(pct: float) -> str:
    """Green → yellow → orange → red gradient, same stops as the firmware."""
    stops = [(0, 200, 0), (255, 255, 0), (255, 140, 0), (255, 34, 0)]
    edges = [0.0, 0.5, 0.75, 1.0]
    if pct <= 0.0:
        rgb = stops[0]
    elif pct >= 1.0:
        rgb = stops[3]
    else:
        rgb = stops[3]
        for i in range(3):
            if pct <= edges[i + 1]:
                t = (pct - edges[i]) / (edges[i + 1] - edges[i])
                rgb = _lerp(stops[i], stops[i + 1], t)
                break
    return "#%02x%02x%02x" % rgb


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _mono_font(size: int, bold: bool = False):
    family = {"Darwin": "Menlo", "Windows": "Consolas"}.get(
        platform.system(), "Courier")
    return (family, size, "bold" if bold else "normal")


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


def _autostart_argv() -> list:
    """Command to relaunch the app at login. Frozen-aware: a packaged exe
    relaunches itself; a dev checkout relaunches python + this script."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--autostart"]
    return [sys.executable, os.path.abspath(__file__), "--autostart"]


def set_autostart_macos(enabled: bool) -> None:
    plist_path = _macos_launch_agent_path()
    if not enabled:
        if os.path.exists(plist_path):
            os.system(f"launchctl unload '{plist_path}' 2>/dev/null")
            os.remove(plist_path)
        return

    args_xml = "\n".join(f"        <string>{a}</string>" for a in _autostart_argv())
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.codelight.monitor</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
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


def set_autostart_windows(enabled: bool) -> None:
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                         winreg.KEY_SET_VALUE) as key:
        if enabled:
            cmd = " ".join(f'"{a}"' for a in _autostart_argv())
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def set_autostart(enabled: bool) -> None:
    system = platform.system()
    if system == "Darwin":
        set_autostart_macos(enabled)
    elif system == "Windows":
        set_autostart_windows(enabled)
    # Other platforms: no-op (autostart checkbox has no effect there).


class DisplayCanvas(tk.Canvas):
    """A 240×240 on-screen mirror of the device display."""

    W = 240
    H = 240
    MARGIN = 6

    def __init__(self, master):
        super().__init__(master, width=self.W, height=self.H,
                         bg=COL_BG, highlightthickness=0, bd=0)
        self.last_payload = {
            "weekly_pct": 0.0, "session_pct": 0.0,
            "weekly_reset": "--", "session_reset": "--",
            "sessions": 0, "tokens_net": 0, "tokens_gross": 0,
            "status": "inactive",
        }
        self.device_online = False
        self.render(self.last_payload)

    def render(self, payload: dict, device_online: bool = None):
        if device_online is not None:
            self.device_online = device_online
        self.last_payload = payload
        self.delete("all")
        m = self.MARGIN

        # Title + clock
        self.create_text(m, 2, anchor="nw", text="CLAUDE CODE",
                         fill=COL_TITLE, font=_mono_font(11))
        self._draw_clock()

        # Meter blocks
        self._draw_meter(22, "Weekly", payload.get("weekly_pct", 0.0),
                         payload.get("weekly_reset", "--"))
        self._draw_meter(65, "Session", payload.get("session_pct", 0.0),
                         payload.get("session_reset", "--"))

        # Sessions + tokens row
        n = payload.get("sessions", 0)
        self.create_text(m, 107, anchor="nw",
                         text=f"{n} session{'' if n == 1 else 's'} active",
                         fill=COL_LABEL, font=_mono_font(11))
        net = payload.get("tokens_net", 0)
        self.create_text(self.W - m, 107, anchor="ne",
                         text=f"{_format_tokens(net)} tok",
                         fill=COL_RESET, font=_mono_font(11))

        # Divider
        self.create_line(0, 126, self.W, 126, fill=COL_BAR_BG)

        # Status box
        self._draw_status(payload.get("status", "inactive"))

    def _draw_meter(self, label_y, label, pct, reset_str):
        m = self.MARGIN
        bar_y = label_y + 18
        bar_w = self.W - m * 2 - 30
        # Row 1: label + reset
        self.create_text(m, label_y, anchor="nw", text=label,
                         fill=COL_LABEL, font=_mono_font(11))
        self.create_text(self.W - m, label_y, anchor="ne", text=reset_str,
                         fill=COL_RESET, font=_mono_font(11))
        # Row 2: bar track + fill
        self.create_rectangle(m, bar_y, m + bar_w, bar_y + 20,
                              fill=COL_BAR_BG, outline="")
        filled = max(0, min(int(pct * bar_w), bar_w))
        if filled > 0:
            self.create_rectangle(m, bar_y, m + filled, bar_y + 20,
                                  fill=_usage_color(pct), outline="")
        self.create_text(self.W - m, bar_y + 2, anchor="ne",
                         text=f"{int(pct * 100)}%",
                         fill=COL_TITLE, font=_mono_font(12))

    def _draw_status(self, status):
        if not self.device_online:
            # Companion still shows local Claude state; a dim dot marks the
            # device as unreachable rather than overriding the status colour.
            pass
        color, label = {
            "working":  (COL_ORANGE, "WORKING"),
            "waiting":  (COL_RED,    "WAITING"),
            "inactive": (COL_GREEN,  "IDLE"),
        }.get(status, (COL_OFFLINE, "IDLE"))

        box = self.H - 128 - 4
        bx = (self.W - box) // 2
        self.create_rectangle(bx, 128, bx + box, 128 + box, fill=color, outline="")
        self.create_text(self.W // 2, 128 + box // 2, text=label,
                         fill="#FFFFFF", font=_mono_font(20, bold=True))
        # Device-reachability dot, top-right corner of the box
        dot = COL_GREEN if self.device_online else "#703030"
        self.create_oval(bx + box - 14, 128 + 6, bx + box - 6, 128 + 14,
                         fill=dot, outline="")

    def _draw_clock(self):
        t = time.strftime("%H:%M:%S")
        self.create_text(self.W - self.MARGIN, 2, anchor="ne", text=t,
                         fill=COL_TITLE, font=_mono_font(11), tags="clock")

    def tick_clock(self):
        """Lightweight per-second clock refresh without a full redraw."""
        self.delete("clock")
        self._draw_clock()


class CodelightApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.stop_event = threading.Event()
        self.thread = None

        cfg = load_config()

        pad = {"padx": 10, "pady": 6}

        # Live mini-display, mirroring the physical device
        preview = tk.Frame(root, bg="#111111")
        preview.pack(fill="x", padx=10, pady=(12, 4))
        self.display = DisplayCanvas(preview)
        self.display.pack(padx=14, pady=14)
        self._tick()

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
            online = error is None and result is not None and result.status_code == 200
            tokens = (f"net {payload['tokens_net']:,} · "
                      f"gross {payload['tokens_gross']:,} (cache incl.)")
            if error is not None:
                text = f"Device offline · {tokens}"
            elif online:
                text = f"Connected · {tokens}"
            else:
                code = result.status_code if result is not None else "?"
                text = f"Device HTTP {code} · {tokens}"
            self.root.after(0, lambda: self._apply_update(payload, online, text))

        def run():
            # No hooks installed: status is inferred from session activity only,
            # so the app never modifies the user's Claude Code configuration.
            try:
                cm.run_monitor_loop(url, headers, on_update=on_update,
                                     stop_event=self.stop_event)
            except Exception as e:
                self.root.after(0, lambda: self._on_thread_error(str(e)))

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Starting…")

    def _apply_update(self, payload, online, text):
        self.display.render(payload, device_online=online)
        self.status_var.set(text)

    def _tick(self):
        self.display.tick_clock()
        self.root.after(1000, self._tick)

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
