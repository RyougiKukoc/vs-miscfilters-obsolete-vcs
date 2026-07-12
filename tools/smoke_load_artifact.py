from __future__ import annotations

import argparse
import os
import site
import sys
import sysconfig
from pathlib import Path


PACKAGE_NAME = "misc"
PLUGIN_BASENAME = "miscfilters"


def resolve_vapoursynth_paths(root: Path | None) -> tuple[Path | None, list[Path], list[Path]]:
    if root is None:
        return None, [], []

    root = root.resolve()
    candidates = [
        (root, root / "vapoursynth"),
        (root / "Lib" / "site-packages", root / "Lib" / "site-packages" / "vapoursynth"),
        (root.parent, root),
    ]
    for sys_path, dll_path in candidates:
        if (dll_path / "libvapoursynth.dll").exists() and (dll_path / "__init__.py").exists():
            return dll_path, [sys_path], [dll_path]
    return None, [root], [root]


def resolve_artifact(root: Path) -> Path:
    root = root.resolve()
    candidates = [
        root,
        root / PACKAGE_NAME,
        root / "vapoursynth" / "plugins" / PACKAGE_NAME,
    ]
    for candidate in candidates:
        if (candidate / f"{PLUGIN_BASENAME}.dll").exists():
            return candidate
    raise FileNotFoundError(root / PACKAGE_NAME / f"{PLUGIN_BASENAME}.dll")


def add_existing_dll_dirs(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            os.add_dll_directory(str(path))


def exercise_filter(core, vs) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    clip = core.std.BlankClip(format=vs.YUV420P8, width=64, height=32, length=5, color=[96, 128, 128])
    averaged = core.misc.AverageFrames([clip, clip], weights=[1.0, 1.0], scale=2.0)
    avg_frame = averaged.get_frame(2)
    avg_stats = core.std.PlaneStats(averaged).get_frame(2).props

    scene = core.misc.SCDetect(clip, threshold=0.1)
    scene_props = scene.get_frame(2).props

    seed = core.std.BlankClip(format=vs.GRAY8, width=32, height=16, length=3, color=[255])
    hysteresis = core.misc.Hysteresis(seed, seed)
    hyst_frame = hysteresis.get_frame(1)
    hyst_stats = core.std.PlaneStats(hysteresis).get_frame(1).props

    if averaged.width != 64 or averaged.height != 32 or avg_frame.width != 64 or avg_frame.height != 32:
        raise RuntimeError(
            f"unexpected AverageFrames output size: node={averaged.width}x{averaged.height}, frame={avg_frame.width}x{avg_frame.height}"
        )
    if hysteresis.width != 32 or hysteresis.height != 16 or hyst_frame.width != 32 or hyst_frame.height != 16:
        raise RuntimeError(
            f"unexpected Hysteresis output size: node={hysteresis.width}x{hysteresis.height}, frame={hyst_frame.width}x{hyst_frame.height}"
        )

    return avg_stats, scene_props, hyst_stats


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-load a built MiscFilters artifact with VapourSynth.")
    parser.add_argument("--vapoursynth-root", help="VapourSynth portable root or extracted wheel root.")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--autoload", action="store_true", help="Load through VAPOURSYNTH_EXTRA_PLUGIN_PATH instead of std.LoadPlugin.")
    parser.add_argument("--exercise-filter", action="store_true", help="Create test nodes and request frames.")
    args = parser.parse_args(argv)

    vs_root = Path(args.vapoursynth_root).resolve() if args.vapoursynth_root else None
    artifact_root = Path(args.artifact_dir).resolve()
    artifact = resolve_artifact(artifact_root)

    required = [
        artifact / f"{PLUGIN_BASENAME}.dll",
        artifact / "manifest.vs",
    ]
    for path in required:
        if not path.exists():
            print(f"missing required path: {path}", file=sys.stderr)
            return 1

    _vs_pkg, sys_paths, dll_paths = resolve_vapoursynth_paths(vs_root)
    for path in reversed(sys_paths):
        if path.exists():
            sys.path.insert(0, str(path))

    add_existing_dll_dirs(
        [
            artifact,
            Path(sys.executable).resolve().parent,
            Path(sysconfig.get_paths().get("platlib", "")),
            Path(sysconfig.get_paths().get("purelib", "")),
            *(Path(p) for p in site.getsitepackages()),
            *dll_paths,
        ]
    )

    if args.autoload:
        plugin_root = artifact.parent
        if artifact_root.joinpath("vapoursynth", "plugins").exists():
            plugin_root = artifact_root / "vapoursynth" / "plugins"
        elif artifact_root.joinpath(PACKAGE_NAME).exists():
            plugin_root = artifact_root
        os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = str(plugin_root)

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        print("install VapourSynth into this Python or pass --vapoursynth-root pointing at an extracted wheel", file=sys.stderr)
        return 1

    try:
        flags = 0 if args.autoload else vs.DISABLE_AUTO_LOADING
        env = vs.create_environment(flags=flags)
        core = env.get_core()
    except AttributeError:
        core = vs.core

    if not args.autoload:
        core.std.LoadPlugin(str(artifact / f"{PLUGIN_BASENAME}.dll"))
    if not hasattr(core, "misc"):
        print("core.misc missing after loading artifact", file=sys.stderr)
        return 1

    required_functions = ("SCDetect", "AverageFrames", "Hysteresis")
    for function_name in required_functions:
        if not hasattr(core.misc, function_name):
            print(f"core.misc.{function_name} missing after loading artifact", file=sys.stderr)
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
