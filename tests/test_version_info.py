from __future__ import annotations

import subprocess
from pathlib import Path

from income33.version_info import collect_repo_version_info


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_collect_repo_version_info_reports_non_git_folder(tmp_path):
    info = collect_repo_version_info(tmp_path)

    assert info["repo_path"] == str(tmp_path)
    assert info["repo_is_git"] is False
    assert info["version_status"] == "non_git"
    assert info["git_head"] is None
    assert info["git_up_to_date"] is False


def test_collect_repo_version_info_reports_clean_matching_origin_main(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    head = _commit(repo, "initial")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    info = collect_repo_version_info(repo)

    assert info["repo_is_git"] is True
    assert info["git_head"] == head
    assert info["git_head_short"] == head[:7]
    assert info["git_branch"] == "main"
    assert info["git_origin_main"] == head
    assert info["git_up_to_date"] is True
    assert info["git_dirty"] is False
    assert info["version_status"] == "ok"


def test_collect_repo_version_info_flags_mismatch_and_dirty_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    old_head = _commit(repo, "initial")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    (repo / "README.md").write_text("two\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    new_head = _commit(repo, "second")

    info = collect_repo_version_info(repo)
    assert info["git_head"] == new_head
    assert info["git_origin_main"] == old_head
    assert info["git_up_to_date"] is False
    assert info["version_status"] == "outdated"

    (repo / "local.txt").write_text("local change\n", encoding="utf-8")
    dirty_info = collect_repo_version_info(repo)
    assert dirty_info["git_dirty"] is True
    assert dirty_info["version_status"] == "dirty"
