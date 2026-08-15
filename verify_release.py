"""Verify a released version, its annotated tag, remote head, and identities."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", help="Expected semantic version; defaults to pyproject.toml")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()

    with Path("pyproject.toml").open("rb") as handle:
        declared = str(tomllib.load(handle)["project"]["version"])
    version = args.version or declared
    if version != declared:
        raise SystemExit(f"version mismatch: pyproject={declared}, requested={version}")

    tag = f"v{version}"
    head = git("rev-parse", "HEAD")
    if git("cat-file", "-t", tag) != "tag":
        raise SystemExit(f"{tag} is not an annotated tag")
    tag_target = git("rev-parse", f"{tag}^{{}}")
    ancestor_check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tag_target, head],
        capture_output=True,
    )
    if ancestor_check.returncode != 0:
        raise SystemExit(f"{tag} target {tag_target} is not an ancestor of HEAD {head}")

    identities = sorted(set(git("log", "--format=%an <%ae>", "HEAD").splitlines()))
    expected = "axewhyzed <77388429+axewhyzed@users.noreply.github.com>"
    if identities != [expected]:
        raise SystemExit(f"unexpected reachable identities: {identities}")

    remote_head = git("ls-remote", args.remote, "refs/heads/main").split()[0]
    remote_tag = git("ls-remote", args.remote, f"refs/tags/{tag}^{{}}").split()[0]
    if remote_head != head or remote_tag != head:
        raise SystemExit(
            f"remote mismatch: main={remote_head}, tag={remote_tag}, expected={head}"
        )
    print(f"release verified: {tag} -> {tag_target}; main -> {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
