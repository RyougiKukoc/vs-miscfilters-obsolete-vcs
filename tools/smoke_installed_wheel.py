#!/usr/bin/env python3
"""Smoke-test MiscFilters through normal VapourSynth wheel autoloading."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from smoke_load_artifact import FUNCTIONS, exercise_filters, plugin_suffix


PACKAGE_NAME = "misc"
PLUGIN_BASENAME = "miscfilters"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an installed vapoursynth-misc wheel.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import vapoursynth as vs

    package_dir = Path(vs.__file__).resolve().parent / "plugins" / PACKAGE_NAME
    plugin = package_dir / f"{PLUGIN_BASENAME}{plugin_suffix()}"
    manifest = package_dir / "manifest.vs"
    if not plugin.is_file() or not manifest.is_file():
        raise FileNotFoundError(f"installed wheel payload is incomplete under {package_dir}")

    core = vs.core
    for function_name in FUNCTIONS:
        if not hasattr(core.misc, function_name):
            raise RuntimeError(f"core.misc.{function_name} missing after installed-wheel autoload")
    result: dict[str, object] = {
        "plugin": str(plugin),
        "manifest": str(manifest),
        "functions": list(FUNCTIONS),
        "autoload": True,
    }
    result.update(exercise_filters(core, vs))
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
