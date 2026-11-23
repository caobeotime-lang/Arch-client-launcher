#!/usr/bin/env sh
# Chạy Arch Client từ source. Lần đầu launcher tự cài thư viện còn thiếu.
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then exec "$py" arch_laucher.py "$@"; fi
done
echo "Không tìm thấy Python 3. Cài python3 trước (vd: sudo apt install python3 python3-pip)." >&2
exit 1
