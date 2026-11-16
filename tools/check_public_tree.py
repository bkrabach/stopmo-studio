#!/usr/bin/env python3
"""Check the tracked (or staged) source-only publication boundary, without printing secrets.

This is a guardrail, not a secret scanner or legal clearance. Review the actual diff too.
"""
from __future__ import annotations

import argparse
from pathlib import PurePosixPath
import re
import subprocess

ROOT_FILES = {"README.md", "AGENTS.md", "LICENSE", "THIRD_PARTY.md", "pyproject.toml", ".gitignore"}
SUFFIXES = {"src": {".py"}, "tests": {".py"}, "tools": {".py", ".sh"},
            "styles": {".yaml"}, "docs": {".md"}}
PATTERNS = {
    "personal home path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+|[A-Z]:\\Users\\[A-Za-z0-9_.-]+"),
    "private network address": re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential-like token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{32,}|AKIA[A-Z0-9]{16})\b"),
    "email address": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="inspect index bytes, not working files")
    args = parser.parse_args()
    paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    bad, count = [], 0
    for name in filter(None, paths):
        count += 1
        path = PurePosixPath(name)
        allowed = (name in ROOT_FILES or name == ".github/workflows/ci.yml"
                   or path.parts[0] in SUFFIXES and path.suffix in SUFFIXES[path.parts[0]])
        if not allowed:
            bad.append((name, "not in the source-only allowlist"))
            continue
        mode = subprocess.check_output(["git", "ls-files", "-s", "--", name]).decode().split()[0]
        if mode not in {"100644", "100755"}:
            bad.append((name, "symlink or non-regular entry"))
            continue
        data = subprocess.check_output(["git", "show", f":{name}"]) if args.staged else open(name, "rb").read()
        if len(data) > 500_000 or b"\0" in data:
            bad.append((name, "binary or unexpectedly large file"))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            bad.append((name, "not UTF-8 source text"))
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                bad.append((name, label))
    if not count:
        print("FAIL: no tracked files; nothing was audited")
        return 1
    for name, why in bad:
        print(f"FAIL: {name}: {why}")
    print(f"Source boundary: {count} files checked, {len(bad)} findings. Manual review still required.")
    return int(bool(bad))


if __name__ == "__main__":
    raise SystemExit(main())
