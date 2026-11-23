#!/usr/bin/env sh
# Run Arch Client from source. On first start the launcher installs missing libraries itself.
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then exec "$py" arch_laucher.py "$@"; fi
done
echo "Python 3 not found. Install python3 first (e.g.: sudo apt install python3 python3-pip)." >&2
exit 1
