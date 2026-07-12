from __future__ import annotations

import base64
import csv
import hashlib
import os
import platform
import shutil
import subprocess
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
DEFAULT_PREBUILT_ASSET = "misc-msys2-ucrt64.zip"
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


def _wheel_tag() -> str:
    machine = platform.machine().lower()
    if sys_platform() != "win32" or machine not in {"amd64", "x86_64"}:
        raise RuntimeError(
            "vapoursynth-misc source/VCS installs currently support Windows x86_64 only. "
            "Use the published wheel or release zip on other platforms."
        )
    return "py3-none-win_amd64"


def sys_platform() -> str:
    return os.environ.get("_PYPROJECT_BUILD_PLATFORM") or os.sys.platform


def _default_prebuilt_url(version: str) -> str:
    repository = os.environ.get("MISC_PREBUILT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    tag = os.environ.get("MISC_PREBUILT_TAG") or f"v{version}"
    asset = os.environ.get("MISC_PREBUILT_ASSET_NAME") or DEFAULT_PREBUILT_ASSET
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _prebuilt_source() -> str:
    return os.environ.get("MISC_PREBUILT_URL") or _default_prebuilt_url(_project_version())


def _copy_local_prebuilt(source: Path, destination: Path) -> None:
    if source.is_dir():
        raise RuntimeError(
            f"MISC_PREBUILT_URL points to a directory ({source}). "
            f"Pass a {DEFAULT_PREBUILT_ASSET} zip file instead."
        )
    shutil.copy2(source, destination)


def _download_with_urllib(source: str, destination: Path) -> None:
    request = urllib.request.Request(source, headers={"User-Agent": "vapoursynth-misc-build-backend"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _download_with_curl(source: str, destination: Path) -> None:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise FileNotFoundError("curl not found")
    subprocess.run(
        [curl, "-L", "--fail", "--silent", "--show-error", "-o", str(destination), source],
        cwd=ROOT,
        check=True,
    )


def _download_with_powershell(source: str, destination: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or shutil.which("pwsh")
    if not powershell:
        raise FileNotFoundError("powershell not found")
    subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-Command",
            "$ProgressPreference='SilentlyContinue'; "
            f"Invoke-WebRequest -Uri '{source}' -OutFile '{destination}'",
        ],
        cwd=ROOT,
        check=True,
    )


def _fetch_prebuilt_archive(source: str, destination: Path) -> None:
    candidate = Path(source)
    if candidate.exists():
        _copy_local_prebuilt(candidate, destination)
        return

    downloaders = [_download_with_urllib, _download_with_curl, _download_with_powershell]
    last_exc: Exception | None = None
    for downloader in downloaders:
        try:
            downloader(source, destination)
            return
        except Exception as exc:  # pragma: no cover - exercised by environment-specific fallbacks
            last_exc = exc

    raise RuntimeError(
        "Failed to download the prebuilt vapoursynth-misc release asset from "
        f"{source!r}. Check network access to GitHub or set MISC_PREBUILT_URL "
        f"to a local {DEFAULT_PREBUILT_ASSET} file and retry."
    ) from last_exc


def _extract_prebuilt_package(archive_path: Path, staging_root: Path) -> Path:
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
            out_path = staging_root / PACKAGE_NAME / relative
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    package_dir = staging_root / PACKAGE_NAME
    required = [
        package_dir / f"{PLUGIN_BASENAME}.dll",
        package_dir / "manifest.vs",
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    return package_dir


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

    license_files = project.get("license-files", [])
    for license_file in license_files:
        lines.append(f"License-File: {license_file}")

    lines.append("")
    return "\n".join(lines)


def _wheel_file_text() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: vapoursynth-misc custom backend",
            "Root-Is-Purelib: false",
            f"Tag: {_wheel_tag()}",
            "",
        ]
    )


def _prepare_dist_info(parent: Path) -> Path:
    dist_info = parent / _dist_info_dirname()
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(_metadata_text(), encoding="utf-8", newline="\n")
    (dist_info / "WHEEL").write_text(_wheel_file_text(), encoding="utf-8", newline="\n")
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
            rel = path.relative_to(package_dir).as_posix()
            contents.append((path, f"vapoursynth/plugins/{PACKAGE_NAME}/{rel}"))

    dist_info = staging_root / _dist_info_dirname()
    for path in sorted(dist_info.rglob("*")):
        if path.is_file():
            rel = path.relative_to(dist_info).as_posix()
            contents.append((path, f"{_dist_info_dirname()}/{rel}"))

    return contents


def _wheel_filename() -> str:
    return f"{_distribution_name()}-{_project_version()}-{_wheel_tag()}.whl"


def _write_wheel(wheel_path: Path, staging_root: Path) -> None:
    contents = _build_wheel_contents(staging_root)
    record_rows: list[tuple[str, str, str]] = []

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src, dst in contents:
            zf.write(src, dst)
            digest, size = _record_digest(src)
            record_rows.append((dst, digest, str(size)))

        record_path = f"{_dist_info_dirname()}/RECORD"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False) as handle:
            writer = csv.writer(handle, lineterminator="\n")
            for row in record_rows:
                writer.writerow(row)
            writer.writerow((record_path, "", ""))
            temp_record = Path(handle.name)

        try:
            zf.write(temp_record, record_path)
        finally:
            temp_record.unlink(missing_ok=True)


def _build_from_prebuilt(wheel_directory: str) -> str:
    Path(wheel_directory).mkdir(parents=True, exist_ok=True)
    source = _prebuilt_source()

    with tempfile.TemporaryDirectory(prefix="vapoursynth-misc-wheel-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        archive_path = temp_dir / DEFAULT_PREBUILT_ASSET
        _fetch_prebuilt_archive(source, archive_path)
        _extract_prebuilt_package(archive_path, temp_dir)
        _prepare_dist_info(temp_dir)

        wheel_name = _wheel_filename()
        wheel_path = Path(wheel_directory) / wheel_name
        _write_wheel(wheel_path, temp_dir)
        return wheel_name


def get_requires_for_build_wheel(config_settings=None) -> list[str]:
    del config_settings
    return []


def get_requires_for_build_sdist(config_settings=None) -> list[str]:
    del config_settings
    return []


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings=None) -> str:
    del config_settings
    dist_info = _prepare_dist_info(Path(metadata_directory))
    return dist_info.name


def build_wheel(wheel_directory: str, config_settings=None, metadata_directory=None) -> str:
    del config_settings, metadata_directory
    return _build_from_prebuilt(wheel_directory)


def build_sdist(sdist_directory: str, config_settings=None) -> str:
    del config_settings
    Path(sdist_directory).mkdir(parents=True, exist_ok=True)
    sdist_name = f"{_distribution_name()}-{_project_version()}.tar.gz"
    sdist_path = Path(sdist_directory) / sdist_name

    with tarfile.open(sdist_path, "w:gz") as tf:
        prefix = f"{_distribution_name()}-{_project_version()}"
        for relative in SDIST_INCLUDE:
            src = ROOT / relative
            if not src.exists():
                continue
            if src.is_dir():
                for path in sorted(src.rglob("*")):
                    if path.is_file():
                        tf.add(path, arcname=f"{prefix}/{path.relative_to(ROOT).as_posix()}")
            else:
                tf.add(src, arcname=f"{prefix}/{src.relative_to(ROOT).as_posix()}")

    return sdist_name
