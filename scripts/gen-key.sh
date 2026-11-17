#!/usr/bin/env bash
# Prints a new PGA_ENCRYPTION_KEY: 32 random bytes, base64-encoded (AES-256-GCM).
# Paste the output into your .env. Never commit it, never share it in chat.
set -euo pipefail
openssl rand -base64 32
