from __future__ import annotations

import argparse
from pathlib import Path

from income33.release_zip import collect_release_files, create_release_zip, default_release_zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a 33income release zip archive")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="33income project root path",
    )
    parser.add_argument(
        "--output",
        default="",
        help="output zip path (default: dist/33income-release-<timestamp>.zip)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    if args.output:
        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = project_root / output_path
    else:
        output_path = default_release_zip_path(project_root)

    files = collect_release_files(project_root)
    file_count = create_release_zip(project_root, output_path, files=files)

    print(f"[OK] release zip created: {output_path}")
    print(f"[OK] files included: {file_count}")


if __name__ == "__main__":
    main()
