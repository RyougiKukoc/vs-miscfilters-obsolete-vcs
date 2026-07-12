from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPS = ROOT / "_deps"
DEFAULT_BUILD = ROOT / "build-ci-msys2"
DEFAULT_DIST = ROOT / "dist" / "msys2-ucrt64"
VAPOURSYNTH_VERSION = "77"
PACKAGE_NAME = "misc"
PLUGIN_BASENAME = "miscfilters"

SYSTEM_DLLS = {
    "advapi32.dll",
    "cfgmgr32.dll",
    "comdlg32.dll",
    "gdi32.dll",
    "kernel32.dll",
    "oleaut32.dll",
    "ole32.dll",
    "shell32.dll",
    "user32.dll",
    "version.dll",
    "winspool.drv",
    "ws2_32.dll",
    "bcrypt.dll",
    "msvcrt.dll",
    "ntdll.dll",
}


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def find_tool(name: str, path: str | None = None) -> str:
    found = shutil.which(name, path=path)
    if found:
        return found
    python_scripts = Path(sys.executable).resolve().parent / "Scripts" / f"{name}.exe"
    if python_scripts.exists():
        return str(python_scripts)
    raise RuntimeError(f"{name} is not on PATH")


def prepend_path_entries(env: dict[str, str], entries: list[Path]) -> None:
    parts = [str(entry) for entry in entries if entry.exists()]
    if not parts:
        return
    existing = env.get("PATH")
    env["PATH"] = os.pathsep.join(parts + ([existing] if existing else []))


def candidate_msys2_prefixes(env: dict[str, str]) -> list[Path]:
    prefixes: list[Path] = []
    msystem_prefix = env.get("MSYSTEM_PREFIX")
    if msystem_prefix:
        prefixes.append(Path(msystem_prefix))
    prefixes.extend(
        [
            ROOT.parents[2] / "msys2" / "ucrt64",
            Path("/ucrt64"),
            Path(r"C:\msys64\ucrt64"),
            Path(r"C:\msys64\mingw64"),
        ]
    )

    seen: set[str] = set()
    unique: list[Path] = []
    for prefix in prefixes:
        key = str(prefix).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(prefix)
    return unique


def resolve_vapoursynth_package(root: Path) -> Path:
    root = root.resolve()
    if (root / "vapoursynth" / "include" / "VapourSynth4.h").exists():
        return root / "vapoursynth"
    if (root / "Lib" / "site-packages" / "vapoursynth" / "include" / "VapourSynth4.h").exists():
        return root / "Lib" / "site-packages" / "vapoursynth"
    if (root / "include" / "VapourSynth4.h").exists():
        return root
    raise FileNotFoundError(root / "vapoursynth" / "include" / "VapourSynth4.h")


def write_vapoursynth_pc(pc_dir: Path, vs_pkg: Path) -> Path:
    pc_dir.mkdir(parents=True, exist_ok=True)
    prefix = vs_pkg.resolve().as_posix()
    pc = pc_dir / "vapoursynth.pc"
    pc.write_text(
        "\n".join(
            [
                f"prefix={prefix}",
                "libdir=${prefix}",
                "includedir=${prefix}/include",
                "",
                "Name: vapoursynth",
                "Description: VapourSynth R77 wheel headers for MSYS2 builds",
                f"Version: {VAPOURSYNTH_VERSION}",
                "Libs:",
                "Cflags: -I${includedir}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    return pc


def dll_dependencies(objdump: str, dll: Path) -> list[str]:
    completed = subprocess.run(
        [objdump, "-p", str(dll)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    deps: list[str] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if line.startswith("DLL Name: "):
            deps.append(line.removeprefix("DLL Name: "))
    return deps


def collect_runtime_dlls(pkg_dir: Path, search_dirs: list[Path], tool_path: str | None) -> None:
    objdump = find_tool("objdump", tool_path)
    queue = sorted(pkg_dir.glob("*.dll"))
    seen: set[str] = set()
    while queue:
        dll = queue.pop(0)
        key = dll.name.lower()
        if key in seen:
            continue
        seen.add(key)
        for dep in dll_dependencies(objdump, dll):
            dep_key = dep.lower()
            if dep_key in SYSTEM_DLLS or dep_key.startswith("api-ms-win-"):
                continue
            dst = pkg_dir / dep
            if dst.exists():
                if dep_key not in seen:
                    queue.append(dst)
                continue
            for search_dir in search_dirs:
                src = search_dir / dep
                if src.exists():
                    shutil.copy2(src, dst)
                    queue.append(dst)
                    break


def find_built_plugin(build_dir: Path) -> Path:
    for candidate in [
        build_dir / f"{PLUGIN_BASENAME}.dll",
        build_dir / f"lib{PLUGIN_BASENAME}.dll",
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(build_dir / f"{PLUGIN_BASENAME}.dll")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build and package MiscFilters with MSYS2 UCRT64.")
    parser.add_argument("--deps-dir", default=str(DEFAULT_DEPS))
    parser.add_argument("--build-dir", default=str(DEFAULT_BUILD))
    parser.add_argument("--dist-dir", default=str(DEFAULT_DIST))
    parser.add_argument("--vapoursynth-root")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)

    deps = Path(args.deps_dir).resolve()
    build_dir = Path(args.build_dir).resolve()
    dist_dir = Path(args.dist_dir).resolve()
    pkg_dir = dist_dir / PACKAGE_NAME
    vs_root = Path(args.vapoursynth_root).resolve() if args.vapoursynth_root else deps / "vapoursynth-wheel-R77"
    vs_pkg = resolve_vapoursynth_package(vs_root)

    for path in [
        vs_pkg / "include" / "VapourSynth4.h",
        vs_pkg / "include" / "VSHelper4.h",
        vs_pkg / "libvapoursynth.dll",
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    if args.clean and build_dir.exists():
        shutil.rmtree(build_dir)
    if args.clean and dist_dir.exists():
        shutil.rmtree(dist_dir)
    needs_reconfigure = build_dir.exists()

    env = os.environ.copy()
    msys2_prefixes = candidate_msys2_prefixes(env)
    prepend_path_entries(
        env,
        [
            *(prefix / "bin" for prefix in msys2_prefixes),
            *(prefix.parent / "usr" / "bin" for prefix in msys2_prefixes),
        ],
    )

    pc_dir = vs_pkg / "lib" / "pkgconfig"
    write_vapoursynth_pc(pc_dir, vs_pkg)
    pc_paths = [str(pc_dir.resolve())]
    existing_pc = env.get("PKG_CONFIG_PATH")
    if existing_pc:
        pc_paths.append(existing_pc)
    env["PKG_CONFIG_PATH"] = os.pathsep.join(pc_paths)

    if "CC" not in env:
        env["CC"] = find_tool("gcc", env.get("PATH"))
    if "CXX" not in env:
        env["CXX"] = find_tool("g++", env.get("PATH"))
    if "PKG_CONFIG" not in env:
        env["PKG_CONFIG"] = find_tool("pkg-config", env.get("PATH"))

    meson = find_tool("meson", env.get("PATH"))
    find_tool("ninja", env.get("PATH"))

    setup_cmd = [
        meson,
        "setup",
        str(build_dir),
        str(ROOT),
        "--backend",
        "ninja",
        "--buildtype",
        "release",
    ]
    if needs_reconfigure:
        setup_cmd.insert(2, "--reconfigure")
    run(setup_cmd, cwd=ROOT, env=env)
    run([meson, "compile", "-C", str(build_dir), "--verbose"], cwd=ROOT, env=env)

    pkg_dir.mkdir(parents=True, exist_ok=True)
    built_plugin = find_built_plugin(build_dir)
    shutil.copy2(built_plugin, pkg_dir / f"{PLUGIN_BASENAME}.dll")
    (pkg_dir / "manifest.vs").write_text(f"[VapourSynth Manifest V1]\n{PLUGIN_BASENAME}\n", encoding="ascii", newline="\n")
    if (ROOT / "LICENSE").exists():
        shutil.copy2(ROOT / "LICENSE", pkg_dir / "LICENSE")

    search_dirs = [Path(p) for p in env.get("PATH", "").split(os.pathsep) if p]
    collect_runtime_dlls(pkg_dir, search_dirs, env.get("PATH"))

    print(f"artifact_dir={dist_dir}")
    for path in sorted(pkg_dir.iterdir()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
