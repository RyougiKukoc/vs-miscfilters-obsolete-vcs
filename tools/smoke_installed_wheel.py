from __future__ import annotations

import argparse
import os
import site
import sys
import sysconfig
from pathlib import Path


PACKAGE_NAME = "misc"
PLUGIN_BASENAME = "miscfilters"


def add_existing_dll_dirs(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            os.add_dll_directory(str(path))


def exercise_filter(core, vs) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    clip = core.std.BlankClip(format=vs.YUV420P8, width=64, height=32, length=5, color=[96, 128, 128])
    averaged = core.misc.AverageFrames([clip, clip], weights=[1.0, 1.0], scale=2.0)
    avg_stats = core.std.PlaneStats(averaged).get_frame(2).props

    scene = core.misc.SCDetect(clip, threshold=0.1)
    scene_props = scene.get_frame(2).props

    seed = core.std.BlankClip(format=vs.GRAY8, width=32, height=16, length=3, color=[255])
    hysteresis = core.misc.Hysteresis(seed, seed)
    hyst_stats = core.std.PlaneStats(hysteresis).get_frame(1).props

    return avg_stats, scene_props, hyst_stats


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an installed vapoursynth-misc wheel.")
    parser.add_argument("--exercise-filter", action="store_true", help="Create test nodes and request frames.")
    args = parser.parse_args(argv)

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        return 1

    vs_pkg = Path(vs.__file__).resolve().parent
    plugin_dir = vs_pkg / "plugins" / PACKAGE_NAME
    plugin_candidates = [
        plugin_dir / f"{PLUGIN_BASENAME}.dll",
        plugin_dir / f"{PLUGIN_BASENAME}.so",
        plugin_dir / f"{PLUGIN_BASENAME}.dylib",
    ]
    plugin_path = next((path for path in plugin_candidates if path.exists()), None)
    if plugin_path is None:
        print(f"missing installed plugin under {plugin_dir}", file=sys.stderr)
        return 1
    manifest = plugin_dir / "manifest.vs"
    if not manifest.exists():
        print(f"missing installed file: {manifest}", file=sys.stderr)
        return 1

    add_existing_dll_dirs(
        [
            plugin_dir,
            vs_pkg,
            Path(sys.executable).resolve().parent,
            Path(sysconfig.get_paths().get("platlib", "")),
            Path(sysconfig.get_paths().get("purelib", "")),
            *(Path(p) for p in site.getsitepackages()),
        ]
    )

    try:
        env = vs.create_environment()
        core = env.get_core()
    except AttributeError:
        core = vs.core

    if not hasattr(core, "misc"):
        print("core.misc missing after installed-wheel autoload", file=sys.stderr)
        return 1

    required_functions = ("SCDetect", "AverageFrames", "Hysteresis")
    for function_name in required_functions:
        if not hasattr(core.misc, function_name):
            print(f"core.misc.{function_name} missing after installed-wheel autoload", file=sys.stderr)
            return 1
        print(getattr(core.misc, function_name))

    if args.exercise_filter:
        try:
            avg_stats, scene_props, hyst_stats = exercise_filter(core, vs)
        except Exception as exc:
            print(f"filter exercise failed: {exc}", file=sys.stderr)
            return 1

        print(f"AverageFrames PlaneStatsMin={avg_stats['PlaneStatsMin']}")
        print(f"AverageFrames PlaneStatsMax={avg_stats['PlaneStatsMax']}")
        print(f"AverageFrames PlaneStatsAverage={avg_stats['PlaneStatsAverage']}")
        print(f"SCDetect _SceneChangePrev={scene_props['_SceneChangePrev']}")
        print(f"SCDetect _SceneChangeNext={scene_props['_SceneChangeNext']}")
        print(f"Hysteresis PlaneStatsMin={hyst_stats['PlaneStatsMin']}")
        print(f"Hysteresis PlaneStatsMax={hyst_stats['PlaneStatsMax']}")
        print(f"Hysteresis PlaneStatsAverage={hyst_stats['PlaneStatsAverage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
