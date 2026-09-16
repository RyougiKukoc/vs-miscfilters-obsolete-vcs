# vapoursynth-misc

`vapoursynth-misc` packages the API4-era Miscellaneous Filters plugin for VapourSynth.

The plugin registers under `core.misc` and currently exposes:

- `core.misc.SCDetect`
- `core.misc.AverageFrames`
- `core.misc.Hysteresis`

## Install

The preferred install path is the named VCS package:

```powershell
python -m pip install -v "vapoursynth-misc @ git+https://github.com/RyougiKukoc/vs-miscfilters-obsolete-vcs.git"
```

On Windows x86_64, the build hook first reuses the tested Release asset
`misc-msys2-ucrt64.zip`. On Linux x86_64, it first reuses
`misc-linux-x86_64.zip`, built for the VapourSynth R79
`manylinux_2_27_x86_64` runtime baseline. Both assets contain the same
`miscfilters` module and `core.misc` namespace.

When the matching Release asset is unavailable, or when
`MISC_FORCE_BUILD=1` is set, the hook performs a native Meson build. The
isolated build dependencies include VapourSynth R79, Meson, and Ninja. A
caller may point at an extracted compatible wheel with
`MISC_VAPOURSYNTH_ROOT`; its `pkgconfig` directory is prepended to, not used
instead of, an existing `PKG_CONFIG_PATH`. macOS intentionally has no Release
asset and follows this native fallback path.

## Release package layout

Published Windows and Linux release zips keep the tested plugin package directory:

```text
misc/
  manifest.vs
  miscfilters.dll | miscfilters.so
  LICENSE
  ...platform runtime files when needed
```

The manifest loads the platform-native `miscfilters` module, while the VapourSynth namespace remains `core.misc`.

The Release tag is always `v<project.version>`; version `2.1` maps to `v2.1`.

## Source build notes

This repository also keeps the upstream Meson and Visual Studio project files. Windows
CI validates MSYS2/UCRT64 and Linux CI builds the R79-compatible payload in a conservative
manylinux image. A native source build requires a C++14 compiler, Meson/Ninja, and an
API4 VapourSynth R79 SDK; no plugin runtime files beyond the host VapourSynth runtime and
standard system C++ runtime are bundled.

Filter behavior reference text remains in [docs/misc.rst](docs/misc.rst).
