# Building the Codelight companion app

The companion is a small Tkinter app that reads Claude Code session activity
and token usage and (optionally) pushes it to a Codelight device. It can run as
a plain Python script or be packaged into a standalone app for people who don't
have Python.

## Run from source (developers)

Requires **Python 3.10+** (the system `python3` on older macOS is too old —
use Homebrew's `python3.12` or similar).

```sh
python3.12 -m venv .venv
.venv/bin/pip install requests
.venv/bin/python codelight_gui.py          # GUI
.venv/bin/python claude_monitor.py --dry-run   # CLI, prints payload
```

The app reads only Claude Code's own files. It does **not** modify your Claude
configuration. (Opt in to hook-based working/waiting detection with
`claude_monitor.py --install-hooks`, which edits `~/.claude/settings.json`.)

## Build a standalone app

```sh
pip install -r requirements-build.txt
pyinstaller --noconfirm codelight.spec
```

Output:
- macOS → `dist/Codelight.app`
- Windows → `dist/Codelight/Codelight.exe`

## Automated cross-platform builds

`.github/workflows/build.yml` builds both macOS and Windows on every `v*` tag
(or via "Run workflow"). Download the `Codelight-macos` / `Codelight-windows`
artifacts from the run.

## ⚠️ Code signing — required before gifting

The CI artifacts are **unsigned**. When a recipient downloads the zip from the
internet, the OS quarantines it:

- **macOS**: Gatekeeper shows *"Codelight can't be opened because Apple cannot
  check it for malicious software."* Workarounds for the recipient: right-click
  the app → **Open** → **Open**, or `xattr -dr com.apple.quarantine Codelight.app`.
  The real fix is signing + notarizing with an Apple Developer ID ($99/yr).
- **Windows**: SmartScreen shows *"Windows protected your PC."* The recipient
  clicks **More info → Run anyway**. The real fix is an Authenticode signing
  certificate.

For a polished gift, sign and notarize before distributing so recipients can
just double-click.
