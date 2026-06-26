#!/bin/bash
# Sign the built Codelight.app with a stable self-signed identity.
#
# Why self-signed: it gives the app a *stable* code identity, so the macOS
# Keychain "Always Allow" grant (needed to read the Claude desktop quota token)
# persists across rebuilds. It does NOT remove the Gatekeeper "unverified
# developer" warning on other machines — for that you need a Developer ID
# certificate (Apple Developer Program) and notarization.
#
# One-time setup: create the self-signed code-signing certificate.
#   1. Open Keychain Access → Certificate Assistant → Create a Certificate…
#   2. Name: "Codelight Self-Signed", Identity Type: Self Signed Root,
#      Certificate Type: Code Signing. Create.
#   (Or script it with openssl + `security import` + `security add-trusted-cert`.)
#
# Then build and run this script:
#   pyinstaller --noconfirm codelight.spec
#   ./sign-macos.sh
set -e

IDENTITY="${CODELIGHT_SIGN_IDENTITY:-Codelight Self-Signed}"
APP="${1:-dist/Codelight.app}"

if ! security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
    echo "Code-signing identity '$IDENTITY' not found. See setup notes in this script." >&2
    exit 1
fi

echo "Signing $APP with '$IDENTITY'…"
codesign --force --deep --sign "$IDENTITY" --timestamp=none "$APP"
codesign --verify --deep --verbose=2 "$APP"
echo "Done. '$APP' is signed and satisfies its Designated Requirement."
