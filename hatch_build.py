from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging import tags


ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "misc"
PLUGIN_BASENAME = "miscfilters"
DEFAULT_REPOSITORY = "RyougiKukoc/vs-miscfilters-obsolete-vcs"
DEFAULT_PREBUILT_ASSET = "misc-msys2-ucrt64.zip"


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"", "0", "false", "no", "off"})


def _project_version() -> str:
    override = os.environ.get("MISC_PREBUILT_VERSION")
    if override:
        return override
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("project.version is missing from pyproject.toml")
    return version


def _default_prebuilt_url(version: str) -> str:
    repository = os.environ.get("MISC_PREBUILT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    tag = os.environ.get("MISC_PREBUILT_TAG") or f"v{version}"
    asset = os.environ.get("MISC_PREBUILT_ASSET_NAME") or DEFAULT_PREBUILT_ASSET
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _prebuilt_source(version: str) -> tuple[str, bool]:
    explicit = os.environ.get("MISC_PREBUILT_URL")
    if explicit:
        return explicit, True
    return _default_prebuilt_url(version), False


def _supports_prebuilt() -> bool:
    return sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}


def _fetch_prebuilt_archive(source: str, destination: Path) -> None:
    candidate = Path(source)
    if candidate.exists():
        shutil.copy2(candidate, destination)
        return

    request = urllib.request.Request(source, headers={"User-Agent": "vapoursynth-misc-build-hook"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _stage_package_from_zip(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        package_members = [
            name
            for name in zf.namelist()
            if name.replace("\\", "/").startswith(f"{PACKAGE_NAME}/") and not name.endswith("/")
        ]
        if not package_members:
            raise FileNotFoundError(f"prebuilt archive does not contain a {PACKAGE_NAME}/ package directory")

        for member in package_members:
            normalized = member.replace("\\", "/")
            relative = normalized.split("/", 1)[1]
            out_path = target_dir / relative
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    plugin_path = None
    for suffix in (".dll", ".so", ".dylib"):
        candidate = target_dir / f"{PLUGIN_BASENAME}{suffix}"
        if candidate.exists():
            plugin_path = candidate
            break
    if plugin_path is None:
        raise FileNotFoundError(f"prebuilt archive did not provide {PLUGIN_BASENAME}.dll/.so/.dylib")

    manifest = target_dir / "manifest.vs"
    if not manifest.exists():
        manifest.write_text(f"[VapourSynth Manifest V1]\n{PLUGIN_BASENAME}\n", encoding="ascii", newline="\n")


def _stage_prebuilt_plugin(version: str, target_dir: Path) -> bool:
    if _truthy(os.environ.get("MISC_FORCE_BUILD")):
        print("Misc wheel build: skipping prebuilt asset because MISC_FORCE_BUILD is set")
        return False
    if not _supports_prebuilt():
        print("Misc wheel build: prebuilt release asset path only applies to Windows x86_64; falling back to local build")
        return False

    source, explicit = _prebuilt_source(version)
    asset_name = Path(source).name or DEFAULT_PREBUILT_ASSET
    try:
        with tempfile.TemporaryDirectory(prefix="misc-prebuilt-") as temp_dir_text:
            archive_path = Path(temp_dir_text) / asset_name
            _fetch_prebuilt_archive(source, archive_path)
            _stage_package_from_zip(archive_path, target_dir)
    except Exception as exc:
        if explicit:
            raise RuntimeError(f"failed to use explicit Misc prebuilt asset {source!r}") from exc
        print(f"Misc wheel build: prebuilt asset unavailable at {source}; falling back to local build ({exc})")
        return False

    print(f"Misc wheel build: using prebuilt release asset {source}")
    return True


def _run(cmd: list[str], *, env: dict[str, str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


def _prepend_path_entries(env: dict[str, str], entries: list[Path]) -> None:
    parts = [str(entry) for entry in entries if entry.exists()]
    if not parts:
        return
    existing = env.get("PATH")
    env["PATH"] = os.pathsep.join(parts + ([existing] if existing else []))


def _meson_command() -> list[str]:
    meson = shutil.which("meson")
    if meson:
        return [meson]

    python_scripts = Path(sys.executable).resolve().parent / "Scripts" / "meson.exe"
    if python_scripts.exists():
        return [str(python_scripts)]

    for module_name in ("mesonbuild", "mesonbuild.mesonmain"):
        module_runner = [sys.executable, "-m", module_name]
        probe = subprocess.run(module_runner + ["--version"], cwd=ROOT, capture_output=True, text=True)
        if probe.returncode == 0:
            return module_runner

    raise FileNotFoundError("meson executable not found and python -m mesonbuild is unavailable")


def _configure_windows_build_env(env: dict[str, str]) -> dict[str, str]:
    if sys.platform != "win32":
        return env

    msystem_prefix = env.get("MSYSTEM_PREFIX")
    path_entries: list[Path] = []
    if msystem_prefix:
        prefix = Path(msystem_prefix)
        path_entries.extend([prefix / "bin", prefix.parent / "usr" / "bin"])
    else:
        workspace_msys2 = ROOT.parents[2] / "msys2"
        path_entries.extend(
            [
                workspace_msys2 / "ucrt64" / "bin",
                workspace_msys2 / "usr" / "bin",
                Path(r"C:\msys64\ucrt64\bin"),
                Path(r"C:\msys64\usr\bin"),
            ]
        )
    _prepend_path_entries(env, path_entries)

    env.setdefault("CC", "gcc")
    env.setdefault("CXX", "g++")
    return env


def _find_built_plugin(build_dir: Path) -> Path:
    for candidate in [
        build_dir / f"{PLUGIN_BASENAME}.dll",
        build_dir / f"{PLUGIN_BASENAME}.so",
        build_dir / f"{PLUGIN_BASENAME}.dylib",
        build_dir / f"lib{PLUGIN_BASENAME}.dll",
        build_dir / f"lib{PLUGIN_BASENAME}.so",
        build_dir / f"lib{PLUGIN_BASENAME}.dylib",
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(build_dir / f"{PLUGIN_BASENAME}.dll")


def _stage_generic_local_build(target_dir: Path) -> None:
    env = _configure_windows_build_env(os.environ.copy())
    build_dir = ROOT / "build-wheel"
    meson = _meson_command()
    _run(meson + ["setup", str(build_dir), str(ROOT), "--backend", "ninja", "--wipe"], env=env)
    _run(meson + ["compile", "-C", str(build_dir)], env=env)

    built_plugin = _find_built_plugin(build_dir)
    shutil.copy2(built_plugin, target_dir / built_plugin.name.replace(f"lib{PLUGIN_BASENAME}", PLUGIN_BASENAME))
    (target_dir / "manifest.vs").write_text(f"[VapourSynth Manifest V1]\n{PLUGIN_BASENAME}\n", encoding="ascii", newline="\n")
    if (ROOT / "LICENSE").exists():
        shutil.copy2(ROOT / "LICENSE", target_dir / "LICENSE")


def _stage_local_build(target_dir: Path) -> None:
    if sys.platform == "win32":
        env = _configure_windows_build_env(os.environ.copy())
        _run([sys.executable, "tools/ci_prepare_msys2.py"], env=env)
        _run(
            [
                sys.executable,
                "tools/ci_build_msys2.py",
                "--clean",
                "--build-dir",
                str(ROOT / "build-wheel-msys2"),
                "--dist-dir",
                str(target_dir.parent),
            ],
            env=env,
        )
        return

    _stage_generic_local_build(target_dir)


class CustomHook(BuildHookInterface[Any]):
    build_dir = ROOT / "build-wheel-msys2"
    dist_dir = ROOT / "vapoursynth" / "plugins" / PACKAGE_NAME

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{next(tags.platform_tags())}"
        project_version = _project_version()

        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(ROOT / "build-wheel", ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)

        if not _stage_prebuilt_plugin(project_version, self.dist_dir):
            _stage_local_build(self.dist_dir)

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        del version, build_data, artifact_path
        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(ROOT / "build-wheel", ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
