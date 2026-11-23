#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_release_notes.py — fill the SHA-256 hashes of the build files into the release notes.

Usage:
    python tools/make_release_notes.py \
        --template .github/releases/linux.md \
        --out dist/release_notes.md \
        dist/ArchClient-1.0.0-linux-x86_64.tar.gz dist/ArchClient-1.0.0-amd64.deb ...

The template contains the SHA256PLACEHOLDER line; the script replaces it with lines of
"<hash>  <file-name>" (same format as sha256sum).
"""
import argparse
import hashlib
from pathlib import Path

MARK = "{{" + "SHA256" + "}}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()

    text = Path(a.template).read_text(encoding="utf-8")
    if MARK not in text:
        raise SystemExit(f"template {a.template} is missing the {MARK} marker")
    lines = [f"{sha256(Path(p))}  {Path(p).name}" for p in a.files]
    text = text.replace(MARK, "\n".join(lines))
    Path(a.out).write_text(text, encoding="utf-8", newline="\n")
    print(f"OK {a.out} (filled hashes for {len(a.files)} files)")


if __name__ == "__main__":
    main()
