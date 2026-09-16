from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "misc"
PLUGIN_BASENAME = "miscfilters"


def platform_suffix() -> str:
    if sys.platform == "win32":
        return ".dll"
    if sys.platform == "darwin":
        return ".dylib"
    return ".so"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create a platform-native MiscFilters plugin package zip.")
    parser.add_argument("--input-dir", default=str(ROOT / "dist" / "msys2-ucrt64"))
    parser.add_argument("--output", default=str(ROOT / "dist" / "misc-msys2-ucrt64.zip"))
    parser.add_argument("--plugin-suffix", default=platform_suffix(), choices=(".dll", ".so", ".dylib"))
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir).resolve()
    output = Path(args.output).resolve()
    package_dir = input_dir / PACKAGE_NAME
    required = [package_dir / f"{PLUGIN_BASENAME}{args.plugin_suffix}", package_dir / "manifest.vs"]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, f"{PACKAGE_NAME}/{path.relative_to(package_dir).as_posix()}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
