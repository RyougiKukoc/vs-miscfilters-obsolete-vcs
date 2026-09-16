#!/usr/bin/env python3
"""Explicitly load a packaged MiscFilters plugin with autoload disabled."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


PACKAGE_NAME = "misc"
PLUGIN_BASENAME = "miscfilters"
FUNCTIONS = ("SCDetect", "AverageFrames", "Hysteresis")


def plugin_suffix() -> str:
    if sys.platform == "win32":
        return ".dll"
    if sys.platform == "darwin":
        return ".dylib"
    return ".so"


def frame_hash(frame: Any) -> str:
    digest = hashlib.sha256()
    for plane in range(frame.format.num_planes):
        digest.update(bytes(frame[plane]))
    return digest.hexdigest()


class IsolatedEnvironmentPolicy:
    """Make the explicit-load gate independent from ambient plugin autoloading."""

    def __init__(self, flags: int) -> None:
        self.api: Any = None
        self.environment: Any = None
        self.flags = flags

    def on_policy_registered(self, api: Any) -> None:
        self.api = api
        self.environment = api.create_environment(self.flags)

    def on_policy_cleared(self) -> None:
        self.api = None
        self.environment = None

    def get_current_environment(self) -> Any:
        return self.environment

    def set_environment(self, environment: Any) -> Any:
        previous = self.environment
        if environment is not None:
            self.environment = environment
        return previous

    def is_alive(self, environment: Any) -> bool:
        return environment is self.environment

    def close(self) -> None:
        if self.api is not None and self.environment is not None:
            self.api.destroy_environment(self.environment)
            self.environment = None


def install_isolated_policy(vs: Any) -> IsolatedEnvironmentPolicy | None:
    if not hasattr(vs, "register_policy") or vs.has_policy():
        return None
    policy = IsolatedEnvironmentPolicy(int(vs.DISABLE_AUTO_LOADING))
    vs.register_policy(policy)
    return policy


def resolve_artifact(artifact_dir: str | None, artifact_zip: str | None) -> tuple[Path, Path | None]:
    if artifact_zip:
        archive_path = Path(artifact_zip).resolve()
        if not archive_path.is_file():
            raise FileNotFoundError(archive_path)
        temporary = Path(tempfile.mkdtemp(prefix="miscfilters-package-"))
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temporary)
        children = [path for path in temporary.iterdir() if path.is_dir()]
        if len(children) != 1 or children[0].name != PACKAGE_NAME:
            raise RuntimeError(f"expected exactly one top-level {PACKAGE_NAME}/ directory in {archive_path}")
        return children[0], temporary

    if artifact_dir is None:
        raise ValueError("--artifact-dir or --artifact-zip is required")
    root = Path(artifact_dir).resolve()
    for candidate in (root, root / PACKAGE_NAME, root / "vapoursynth" / "plugins" / PACKAGE_NAME):
        if (candidate / f"{PLUGIN_BASENAME}{plugin_suffix()}").is_file():
            return candidate, None
    raise FileNotFoundError(root / PACKAGE_NAME / f"{PLUGIN_BASENAME}{plugin_suffix()}")


def exercise_filters(core: Any, vs: Any) -> dict[str, object]:
    clip = core.std.BlankClip(format=vs.YUV420P8, width=64, height=32, length=5, color=[96, 128, 128])
    averaged = core.misc.AverageFrames([clip, clip], weights=[1.0, 1.0], scale=2.0)
    average_frames = {number: averaged.get_frame(number) for number in (0, 2, 4)}
    average_hashes = {str(number): frame_hash(frame) for number, frame in average_frames.items()}
    if len(set(average_hashes.values())) != 1:
        raise RuntimeError(f"static AverageFrames input produced inconsistent hashes: {average_hashes}")
    average_stats = dict(core.std.PlaneStats(averaged).get_frame(2).props)

    scene = core.misc.SCDetect(clip, threshold=0.1)
    scene_frame = scene.get_frame(2)
    scene_props = scene_frame.props
    if scene_props["_SceneChangePrev"] != 0 or scene_props["_SceneChangeNext"] != 0:
        raise RuntimeError(f"static SCDetect clip unexpectedly marked a scene change: {dict(scene_props)}")

    seed = core.std.BlankClip(format=vs.GRAY8, width=32, height=16, length=3, color=[255])
    hysteresis = core.misc.Hysteresis(seed, seed)
    hysteresis_frame = hysteresis.get_frame(1)
    hysteresis_stats = dict(core.std.PlaneStats(hysteresis).get_frame(1).props)

    try:
        core.misc.SCDetect(clip, threshold=1.1)
    except vs.Error:
        invalid_input_rejected = True
    else:
        invalid_input_rejected = False
    if not invalid_input_rejected:
        raise RuntimeError("SCDetect accepted an out-of-range threshold")

    frame = average_frames[2]
    return {
        "width": frame.width,
        "height": frame.height,
        "format": frame.format.name,
        "frames": averaged.num_frames,
        "averageframes_hashes": average_hashes,
        "averageframes_plane_stats": {
            "min": float(average_stats["PlaneStatsMin"]),
            "max": float(average_stats["PlaneStatsMax"]),
            "average": float(average_stats["PlaneStatsAverage"]),
        },
        "scdetect_hash": frame_hash(scene_frame),
        "scdetect_scene_change_prev": int(scene_props["_SceneChangePrev"]),
        "scdetect_scene_change_next": int(scene_props["_SceneChangeNext"]),
        "hysteresis_hash": frame_hash(hysteresis_frame),
        "hysteresis_plane_stats": {
            "min": float(hysteresis_stats["PlaneStatsMin"]),
            "max": float(hysteresis_stats["PlaneStatsMax"]),
            "average": float(hysteresis_stats["PlaneStatsAverage"]),
        },
        "invalid_threshold_rejected": invalid_input_rejected,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Explicitly smoke-test a MiscFilters package directory or zip.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--artifact-dir")
    group.add_argument("--artifact-zip")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    package_dir, temporary = resolve_artifact(args.artifact_dir, args.artifact_zip)
    plugin = package_dir / f"{PLUGIN_BASENAME}{plugin_suffix()}"
    manifest = package_dir / "manifest.vs"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)

    try:
        add_dll_directory = getattr(os, "add_dll_directory", None)
        handles = [add_dll_directory(str(package_dir))] if add_dll_directory is not None else []
        import vapoursynth as vs

        policy = install_isolated_policy(vs)
        core = vs.core
        core.std.LoadPlugin(str(plugin))
        for function_name in FUNCTIONS:
            if not hasattr(core.misc, function_name):
                raise RuntimeError(f"core.misc.{function_name} missing after explicit LoadPlugin")
        result: dict[str, object] = {
            "plugin": str(plugin),
            "manifest": str(manifest),
            "functions": list(FUNCTIONS),
            "explicit_load": True,
        }
        result.update(exercise_filters(core, vs))
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
        return 0
    finally:
        if "policy" in locals() and policy is not None:
            policy.close()
        for handle in locals().get("handles", []):
            handle.close()
        if temporary is not None:
            # Keep extraction available for the current process's failure diagnostics.
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
