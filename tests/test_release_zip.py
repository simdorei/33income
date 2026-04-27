from pathlib import Path
from zipfile import ZipFile

from income33.release_zip import collect_release_files, create_release_zip


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_collect_release_files_excludes_runtime_and_local_files(tmp_path):
    _touch(tmp_path / "README.md")
    _touch(tmp_path / "run_control_tower.bat")
    _touch(tmp_path / "src/income33/__init__.py")
    _touch(tmp_path / "config/control_tower.example.yaml")

    _touch(tmp_path / "data/33income.db")
    _touch(tmp_path / "logs/agent.log")
    _touch(tmp_path / "profiles/sender-01/state.json")
    _touch(tmp_path / "captures/20260427/captures.jsonl")
    _touch(tmp_path / "tmp/cache.txt")
    _touch(tmp_path / ".env")
    _touch(tmp_path / "config/control_tower.yaml")
    _touch(tmp_path / ".git/HEAD")

    files = collect_release_files(tmp_path)
    rel_paths = {str(path.relative_to(tmp_path)).replace("\\", "/") for path in files}

    assert "README.md" in rel_paths
    assert "run_control_tower.bat" in rel_paths
    assert "src/income33/__init__.py" in rel_paths
    assert "config/control_tower.example.yaml" in rel_paths

    assert "data/33income.db" not in rel_paths
    assert "logs/agent.log" not in rel_paths
    assert "profiles/sender-01/state.json" not in rel_paths
    assert "captures/20260427/captures.jsonl" not in rel_paths
    assert "tmp/cache.txt" not in rel_paths
    assert ".env" not in rel_paths
    assert "config/control_tower.yaml" not in rel_paths
    assert ".git/HEAD" not in rel_paths


def test_create_release_zip_contains_only_release_files(tmp_path):
    _touch(tmp_path / "README.md", "readme")
    _touch(tmp_path / "setup_windows.bat", "echo setup")
    _touch(tmp_path / "src/income33/__init__.py", "__version__ = '0.1.0'")
    _touch(tmp_path / "data/33income.db", "db")

    output_zip = tmp_path / "dist/release.zip"
    file_count = create_release_zip(project_root=tmp_path, output_zip_path=output_zip)

    assert output_zip.exists()
    assert file_count == 3

    with ZipFile(output_zip, "r") as archive:
        names = set(archive.namelist())

    assert "README.md" in names
    assert "setup_windows.bat" in names
    assert "src/income33/__init__.py" in names
    assert "data/33income.db" not in names
