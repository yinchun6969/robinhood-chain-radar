#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [[ "${PREFIX:-}" == *"com.termux"* ]] || [[ -d /data/data/com.termux/files/usr ]]; then
  exec bash "$ROOT/install-termux.sh"
fi
if command -v apt-get >/dev/null 2>&1; then
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    exec bash "$ROOT/scripts/ubuntu/install.sh"
  elif command -v sudo >/dev/null 2>&1; then
    exec sudo bash "$ROOT/scripts/ubuntu/install.sh"
  fi
fi
echo "Unsupported environment. Use docs/zh-CN/ANDROID.md or docs/zh-CN/UBUNTU.md."
exit 2
