#!/usr/bin/env python3
"""Fetch the pinned documents, test ROMs and source trees into reference/ and tests/test_roms/.

Nothing fetched here is committed (see .gitignore). Two pin files drive it:

- ``scripts/pinned_files.json``: one entry per file, with its URL, SHA-256 and
  kind. Kinds ``document``, ``manual``, ``hardware-capture`` and ``test-rom`` must
  match their hash exactly; a mismatch is an error and the file is not kept.
  Kinds ``live-wiki`` and ``live-forum`` are snapshots of pages that change
  (NESdev wiki sources, forum threads); a mismatch there is reported as a
  warning and the new bytes are kept, because the snapshot date is what the
  docs cite.
- ``scripts/pinned_repos.json``: one entry per git repository, cloned shallow at
  the pinned revision (sparse where the entry lists paths).

Forum threads are also converted to plain text next to their HTML.

    python scripts/fetch_references.py            # everything missing
    python scripts/fetch_references.py --verify   # hash what is present, fetch nothing
    python scripts/fetch_references.py --no-repos # files only
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "scripts" / "pinned_files.json"
REPOS = ROOT / "scripts" / "pinned_repos.json"
LIVE = {"live-wiki", "live-forum"}
USER_AGENT = "Mozilla/5.0 (famicom-python reference fetch)"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str) -> bytes:
    # nesdev.org answers urllib with 403 whatever the User-Agent, and curl with 200
    # (checked 2026-10-05), so curl does the fetching.
    result = subprocess.run(
        ["curl", "-sSfL", "--max-time", "120", "-A", USER_AGENT, url],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise OSError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def forum_text(raw: str) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.DOTALL)
    text = html.unescape(re.sub(r"<br\s*/?>", "\n", text))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"(\s*\n\s*){2,}", "\n\n", text)


def fetch_files(verify_only: bool) -> int:
    problems = 0
    for entry in json.loads(FILES.read_text(encoding="utf-8")):
        path = ROOT / entry["path"]
        live = entry["kind"] in LIVE
        if path.exists():
            if sha256(path) != entry["sha256"]:
                level = "warning" if live else "ERROR"
                print(f"{level}: {entry['path']} does not match its pin")
                problems += not live
            continue
        if verify_only:
            print(f"missing: {entry['path']}")
            problems += 1
            continue
        try:
            data = download(entry["url"])
        except OSError as error:
            print(f"ERROR: {entry['url']}: {error}")
            problems += 1
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"] and not live:
            print(f"ERROR: {entry['url']} has SHA-256 {digest}, pinned {entry['sha256']}; not kept")
            problems += 1
            continue
        if digest != entry["sha256"]:
            print(f"warning: {entry['path']} changed since the 2026-10-05 snapshot")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(data)
        Path(handle.name).replace(path)
        if entry["kind"] == "live-forum":
            path.with_suffix(".txt").write_text(
                forum_text(data.decode("utf-8", "replace")), encoding="utf-8"
            )
        print(f"fetched {entry['path']}")
    return problems


def fetch_repos(verify_only: bool) -> int:
    problems = 0
    for entry in json.loads(REPOS.read_text(encoding="utf-8")):
        path = ROOT / entry["path"]
        if path.exists():
            head = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if head != entry["rev"]:
                print(f"ERROR: {entry['path']} is at {head}, pinned {entry['rev']}")
                problems += 1
            continue
        if verify_only:
            print(f"missing: {entry['path']}")
            problems += 1
            continue
        path.mkdir(parents=True)
        git = ["git", "-C", str(path)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "remote", "add", "origin", entry["url"]], check=True)
        if entry["sparse"]:
            # The pins are gitignore-style patterns (/dir/, /file*), not cone directories.
            subprocess.run(
                [*git, "sparse-checkout", "set", "--no-cone", *entry["sparse"]], check=True
            )
        subprocess.run(
            [*git, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", entry["rev"]],
            check=True,
        )
        subprocess.run([*git, "checkout", "-q", "FETCH_HEAD"], check=True)
        print(f"cloned {entry['path']} at {entry['rev'][:12]}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--verify", action="store_true", help="check what is present; fetch nothing"
    )
    parser.add_argument("--no-repos", action="store_true", help="skip the git repositories")
    args = parser.parse_args()
    problems = fetch_files(args.verify)
    if not args.no_repos:
        problems += fetch_repos(args.verify)
    print("all pins satisfied" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
