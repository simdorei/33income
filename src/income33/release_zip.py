from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "data",
    "logs",
    "profiles",
    "tmp",
    "dist",
}
EXCLUDED_FILE_NAMES = {
    ".env",
    ".DS_Store",
    "Thumbs.db",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
}
EXCLUDED_RELATIVE_PATHS = {
    "config/control_tower.yaml",
    "config/agent.yaml",
}


def should_include_path(relative_path: Path) -> bool:
    rel = relative_path.as_posix()
    if rel in EXCLUDED_RELATIVE_PATHS:
        return False

    if any(part in EXCLUDED_DIR_NAMES for part in relative_path.parts):
        return False

    if relative_path.name in EXCLUDED_FILE_NAMES:
        return False

    if relative_path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False

    return True


def collect_release_files(project_root: Path) -> list[Path]:
    root = project_root.resolve()
    files: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        relative_path = path.relative_to(root)
        if not should_include_path(relative_path):
            continue

        files.append(path)

    files.sort(key=lambda item: item.relative_to(root).as_posix())
    return files


def default_release_zip_path(project_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    return project_root / "dist" / f"33income-release-{timestamp}.zip"


def create_release_zip(
    project_root: Path,
    output_zip_path: Path,
    files: list[Path] | None = None,
) -> int:
    root = project_root.resolve()
    output_path = output_zip_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    selected_files = files if files is not None else collect_release_files(root)

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in selected_files:
            archive.write(file_path, file_path.relative_to(root).as_posix())

    return len(selected_files)
