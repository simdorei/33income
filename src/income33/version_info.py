from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


DEFAULT_AGENT_VERSION = "0.1.0"


def _default_repo_path() -> Path:
    # src/income33/version_info.py -> repo root when running from source checkout.
    return Path(__file__).resolve().parents[2]


def _run_git(repo_path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def collect_repo_version_info(repo_path: Path | str | None = None) -> dict[str, Any]:
    """Return a secret-free local git/repo version snapshot for heartbeat payloads.

    This intentionally performs no network fetch. It compares the current local
    HEAD with the already-known local `origin/main` ref so heartbeat collection is
    fast and safe on Windows bot PCs.
    """

    requested_path = Path(repo_path).expanduser() if repo_path is not None else _default_repo_path()
    requested_path = requested_path.resolve() if requested_path.exists() else requested_path
    base: dict[str, Any] = {
        "agent_version": DEFAULT_AGENT_VERSION,
        "repo_path": str(requested_path),
        "repo_is_git": False,
        "git_head": None,
        "git_head_short": None,
        "git_branch": None,
        "git_origin_main": None,
        "git_up_to_date": False,
        "git_dirty": False,
        "version_status": "non_git",
    }

    inside_work_tree = _run_git(requested_path, "rev-parse", "--is-inside-work-tree")
    if inside_work_tree != "true":
        return base

    repo_root = _run_git(requested_path, "rev-parse", "--show-toplevel")
    if repo_root:
        base["repo_path"] = repo_root
        git_path = Path(repo_root)
    else:
        git_path = requested_path

    head = _run_git(git_path, "rev-parse", "HEAD")
    branch = _run_git(git_path, "branch", "--show-current")
    origin_main = _run_git(git_path, "rev-parse", "--verify", "origin/main")
    status_porcelain = _run_git(git_path, "status", "--porcelain")

    base.update(
        {
            "repo_is_git": True,
            "git_head": head,
            "git_head_short": head[:7] if head else None,
            "git_branch": branch or None,
            "git_origin_main": origin_main,
            "git_up_to_date": bool(head and origin_main and head == origin_main),
            "git_dirty": bool(status_porcelain),
        }
    )

    if head is None:
        base["version_status"] = "unknown"
    elif base["git_dirty"]:
        base["version_status"] = "dirty"
    elif origin_main is None:
        base["version_status"] = "no_origin_main"
    elif head != origin_main:
        base["version_status"] = "outdated"
    else:
        base["version_status"] = "ok"

    return base
