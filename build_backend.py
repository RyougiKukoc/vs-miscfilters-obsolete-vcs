from __future__ import annotations

import base64
import csv
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "misc"
PLUGIN_BASENAME = "miscfilters"
DEFAULT_REPOSITORY = "RyougiKukoc/vs-miscfilters-obsolete-vcs"
PREBUILT_ASSETS = {
    "win32": "misc-msys2-ucrt64.zip",
    "linux": "misc-linux-x86_64.zip",
}
LINUX_PLATFORM_TAG = "manylinux_2_27_x86_64"
SDIST_INCLUDE = [
    "LICENSE",
    "README.md",
    "build_backend.py",
    "docs",
    "meson.build",
    "msvc_project",
    "pyproject.toml",
    "src",
    "tools",
]


def _project_data() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _project_metadata() -> dict:
    return _project_data()["project"]


def _project_name() -> str:
    return str(_project_metadata()["name"])


def _project_version() -> str:
    override = os.environ.get("MISC_PREBUILT_VERSION")
    if override:
        return override
    return str(_project_metadata()["version"])


def _distribution_name() -> str:
    return _project_name().replace("-", "_")


def _dist_info_dirname() -> str:
    return f"{_distribution_name()}-{_project_version()}.dist-info"


def _platform_name() -> str:
    return os.environ.get("_PYPROJECT_BUILD_PLATFORM") or sys.platform


def _machine_name() -> str:
    return platform.machine().lower()


def _is_x86_64() -> bool:
    return _machine_name() in {"amd64", "x86_64"}


def _plugin_suffix() -> str:
    current = _platform_name()
    if current == "win32":
        return ".dll"
    if current == "darwin":
        return ".dylib"
    if current.startswith("linux"):
        return ".so"
    raise RuntimeError(f"vapoursynth-misc does not support native builds on {current!r}")


def _prebuilt_asset() -> str | None:
    current = _platform_name()
    if current == "win32" and _is_x86_64():
        return PREBUILT_ASSETS["win32"]
    if current.startswith("linux") and _is_x86_64():
        return PREBUILT_ASSETS["linux"]
    return None


def _default_prebuilt_url(version: str, asset: str) -> str:
    repository = os.environ.get("MISC_PREBUILT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    tag = os.environ.get("MISC_PREBUILT_TAG") or f"v{version}"
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _prebuilt_source(version: str, asset: str) -> tuple[str, bool]:
    explicit = os.environ.get("MISC_PREBUILT_URL")
    if explicit:
        return explicit, True
    return _default_prebuilt_url(version, asset), False


def _copy_local_prebuilt(source: Path, destination: Path) -> None:
    if source.is_dir():
        raise RuntimeError(f"MISC_PREBUILT_URL points to a directory ({source}), not a Release zip")
    shutil.copy2(source, destination)


def _fetch_prebuilt_archive(source: str, destination: Path) -> None:
    candidate = Path(source)
    if candidate.exists():
        _copy_local_prebuilt(candidate, destination)
        return

    request = urllib.request.Request(source, headers={"User-Agent": "vapoursynth-misc-build-backend"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _write_manifest(package_dir: Path) -> None:
    (package_dir / "manifest.vs").write_text(
        "[VapourSynth Manifest V1]\n"
        f"{PLUGIN_BASENAME}\n",
        encoding="ascii",
        newline="\n",
    )


def _stage_archive(archive_path: Path, package_dir: Path) -> None:
    prefix = f"{PACKAGE_NAME}/"
    with zipfile.ZipFile(archive_path) as archive:
        members = [
            (name, name.replace("\\", "/"))
            for name in archive.namelist()
            if name.replace("\\", "/").startswith(prefix) and not name.endswith("/")
        ]
        if not members:
            raise FileNotFoundError(f"prebuilt archive does not contain the required {PACKAGE_NAME}/ directory")
        for archive_member, normalized_member in members:
            relative = Path(normalized_member[len(prefix):])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"unsafe archive entry: {normalized_member}")
            destination = package_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(archive_member) as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    expected = package_dir / f"{PLUGIN_BASENAME}{_plugin_suffix()}"
    if not expected.is_file():
        raise FileNotFoundError(f"prebuilt archive did not provide {expected.name}")
    if not (package_dir / "manifest.vs").is_file():
        raise FileNotFoundError("prebuilt archive did not provide manifest.vs")


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"", "0", "false", "no", "off"})


def _stage_prebuilt_package(version: str, package_dir: Path) -> bool:
    if _truthy(os.environ.get("MISC_FORCE_BUILD")):
        print("vapoursynth-misc wheel build: skipping Release asset because MISC_FORCE_BUILD is set")
        return False

    asset = _prebuilt_asset()
    if asset is None:
        print("vapoursynth-misc wheel build: no matching Release asset; falling back to a local native build")
        return False

    source, explicit = _prebuilt_source(version, asset)
    try:
        with tempfile.TemporaryDirectory(prefix="vapoursynth-misc-prebuilt-") as temporary:
            archive_path = Path(temporary) / asset
            _fetch_prebuilt_archive(source, archive_path)
            _stage_archive(archive_path, package_dir)
    except Exception as exc:
        if explicit:
            raise RuntimeError(f"failed to use explicit vapoursynth-misc Release asset {source!r}") from exc
        print(f"vapoursynth-misc wheel build: Release asset unavailable at {source}; falling back to a local native build ({exc})")
        return False

    print(f"vapoursynth-misc wheel build: using prebuilt Release asset {source}")
    return True


def _find_vapoursynth_root() -> Path:
    configured = os.environ.get("MISC_VAPOURSYNTH_ROOT")
    if configured:
        candidates = [Path(configured), Path(configured) / "vapoursynth"]
    else:
        try:
            import vapoursynth
        except ImportError as exc:
            raise RuntimeError(
                "VapourSynth R79 headers are required for a native vapoursynth-misc build. "
                "Install the build requirement or set MISC_VAPOURSYNTH_ROOT to an extracted R79 vapoursynth package."
            ) from exc
        candidates = [Path(vapoursynth.__file__).resolve().parent]

    for candidate in candidates:
        include_dir = candidate / "include"
        pc_file = candidate / "pkgconfig" / "vapoursynth.pc"
        if (include_dir / "VapourSynth4.h").is_file() and (include_dir / "VSHelper4.h").is_file() and pc_file.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "MISC_VAPOURSYNTH_ROOT must contain include/VapourSynth4.h, include/VSHelper4.h, "
        "and pkgconfig/vapoursynth.pc"
    )


def _prepend_pkg_config_path(env: dict[str, str], vapoursynth_root: Path) -> None:
    pkgconfig_dir = vapoursynth_root / "pkgconfig"
    existing = env.get("PKG_CONFIG_PATH")
    env["PKG_CONFIG_PATH"] = os.pathsep.join([str(pkgconfig_dir)] + ([existing] if existing else []))


def _meson_command() -> list[str]:
    found = shutil.which("meson")
    if found:
        return [found]
    command = [sys.executable, "-m", "mesonbuild.mesonmain"]
    probe = subprocess.run(command + ["--version"], cwd=ROOT, capture_output=True, text=True)
    if probe.returncode == 0:
        return command
    raise FileNotFoundError("Meson is required for a native vapoursynth-misc build")


def _find_built_plugin(build_dir: Path) -> Path:
    suffix = _plugin_suffix()
    candidates = [
        build_dir / f"{PLUGIN_BASENAME}{suffix}",
        build_dir / f"lib{PLUGIN_BASENAME}{suffix}",
    ]
    candidates.extend(build_dir.rglob(f"{PLUGIN_BASENAME}{suffix}"))
    candidates.extend(build_dir.rglob(f"lib{PLUGIN_BASENAME}{suffix}"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"native Meson build did not produce {PLUGIN_BASENAME}{suffix}")


def _stage_native_package(package_dir: Path) -> None:
    env = os.environ.copy()
    vapoursynth_root = _find_vapoursynth_root()
    _prepend_pkg_config_path(env, vapoursynth_root)
    meson = _meson_command()

    with tempfile.TemporaryDirectory(prefix="vapoursynth-misc-native-") as temporary:
        build_dir = Path(temporary) / "build"
        subprocess.run(
            meson + ["setup", str(build_dir), str(ROOT), "--buildtype", "release"],
            cwd=ROOT,
            env=env,
            check=True,
        )
        subprocess.run(meson + ["compile", "-C", str(build_dir)], cwd=ROOT, env=env, check=True)
        plugin = _find_built_plugin(build_dir)
        shutil.copy2(plugin, package_dir / f"{PLUGIN_BASENAME}{_plugin_suffix()}")

    _write_manifest(package_dir)
    license_file = ROOT / "LICENSE"
    if license_file.is_file():
        shutil.copy2(license_file, package_dir / license_file.name)
    print(f"vapoursynth-misc wheel build: built native plugin using Meson and {vapoursynth_root}")


def _wheel_tag(used_prebuilt: bool) -> str:
    current = _platform_name()
    if current == "win32" and _is_x86_64():
        return "py3-none-win_amd64"
    if current.startswith("linux") and _is_x86_64() and used_prebuilt:
        platform_tag = os.environ.get("MISC_PLATFORM_TAG") or LINUX_PLATFORM_TAG
        return f"py3-none-{platform_tag}"

    platform_tag = os.environ.get("MISC_PLATFORM_TAG") or sysconfig.get_platform().replace("-", "_").replace(".", "_")
    return f"py3-none-{platform_tag}"


def _metadata_text() -> str:
    project = _project_metadata()
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        f"Summary: {project.get('description', '')}",
    ]
    requires_python = project.get("requires-python")
    if requires_python:
        lines.append(f"Requires-Python: {requires_python}")
    for author in project.get("authors", []):
        name = author.get("name")
        if name:
            lines.append(f"Author: {name}")
    for dependency in project.get("dependencies", []):
        lines.append(f"Requires-Dist: {dependency}")
    for label, url in project.get("urls", {}).items():
        lines.append(f"Project-URL: {label}, {url}")
    for license_file in project.get("license-files", []):
        lines.append(f"License-File: {license_file}")
    lines.append("")
    return "\n".join(lines)


def _wheel_file_text(tag: str) -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: vapoursynth-misc custom backend",
            "Root-Is-Purelib: false",
            f"Tag: {tag}",
            "",
        ]
    )


def _prepare_dist_info(parent: Path, tag: str | None) -> Path:
    dist_info = parent / _dist_info_dirname()
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(_metadata_text(), encoding="utf-8", newline="\n")
    if tag is not None:
        (dist_info / "WHEEL").write_text(_wheel_file_text(tag), encoding="utf-8", newline="\n")
    return dist_info


def _record_digest(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"sha256={encoded}", len(data)


def _build_wheel_contents(staging_root: Path) -> list[tuple[Path, str]]:
    contents: list[tuple[Path, str]] = []
    package_dir = staging_root / PACKAGE_NAME
    for path in sorted(package_dir.rglob("*")):
        if path.is_file():
            contents.append((path, f"vapoursynth/plugins/{PACKAGE_NAME}/{path.relative_to(package_dir).as_posix()}"))
    dist_info = staging_root / _dist_info_dirname()
    for path in sorted(dist_info.rglob("*")):
        if path.is_file():
            contents.append((path, f"{_dist_info_dirname()}/{path.relative_to(dist_info).as_posix()}"))
    return contents


def _wheel_filename(tag: str) -> str:
    return f"{_distribution_name()}-{_project_version()}-{tag}.whl"


def _write_wheel(wheel_path: Path, staging_root: Path) -> None:
    contents = _build_wheel_contents(staging_root)
    record_rows: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, destination in contents:
            archive.write(source, destination)
            digest, size = _record_digest(source)
            record_rows.append((destination, digest, str(size)))
        record_path = f"{_dist_info_dirname()}/RECORD"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False) as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerows(record_rows)
            writer.writerow((record_path, "", ""))
            temporary_record = Path(handle.name)
        try:
            archive.write(temporary_record, record_path)
        finally:
            temporary_record.unlink(missing_ok=True)


def _build_wheel(wheel_directory: str) -> str:
    Path(wheel_directory).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vapoursynth-misc-wheel-") as temporary:
        staging_root = Path(temporary)
        package_dir = staging_root / PACKAGE_NAME
        package_dir.mkdir(parents=True, exist_ok=True)
        used_prebuilt = _stage_prebuilt_package(_project_version(), package_dir)
        if not used_prebuilt:
            _stage_native_package(package_dir)
        tag = _wheel_tag(used_prebuilt)
        _prepare_dist_info(staging_root, tag)
        wheel_name = _wheel_filename(tag)
        _write_wheel(Path(wheel_directory) / wheel_name, staging_root)
        return wheel_name


def get_requires_for_build_wheel(config_settings=None) -> list[str]:
    del config_settings
    return []


def get_requires_for_build_sdist(config_settings=None) -> list[str]:
    del config_settings
    return []


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings=None) -> str:
    del config_settings
    dist_info = _prepare_dist_info(Path(metadata_directory), None)
    return dist_info.name


def build_wheel(wheel_directory: str, config_settings=None, metadata_directory=None) -> str:
    del config_settings, metadata_directory
    return _build_wheel(wheel_directory)


def build_sdist(sdist_directory: str, config_settings=None) -> str:
    del config_settings
    Path(sdist_directory).mkdir(parents=True, exist_ok=True)
    sdist_name = f"{_distribution_name()}-{_project_version()}.tar.gz"
    sdist_path = Path(sdist_directory) / sdist_name
    with tarfile.open(sdist_path, "w:gz") as archive:
        prefix = f"{_distribution_name()}-{_project_version()}"
        for relative in SDIST_INCLUDE:
            source = ROOT / relative
            if not source.exists():
                continue
            if source.is_dir():
                for path in sorted(source.rglob("*")):
                    if path.is_file():
                        archive.add(path, arcname=f"{prefix}/{path.relative_to(ROOT).as_posix()}")
            else:
                archive.add(source, arcname=f"{prefix}/{source.relative_to(ROOT).as_posix()}")
    return sdist_name
