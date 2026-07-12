# vapoursynth-misc

`vapoursynth-misc` packages the API4-era Miscellaneous Filters plugin for VapourSynth.

The plugin registers under `core.misc` and currently exposes:

- `core.misc.SCDetect`
- `core.misc.AverageFrames`
- `core.misc.Hysteresis`

## Windows install

The preferred install path is the named VCS package:

```powershell
python -m pip install -v "vapoursynth-misc @ git+https://github.com/RyougiKukoc/vs-miscfilters-obsolete-vcs.git"
```

On Windows x86_64, the build hook first tries to reuse the tested GitHub Release asset
`misc-msys2-ucrt64.zip`. If no matching release asset is available, it falls back to a
local MSYS2/UCRT64 Meson build.

## Release package layout

Published Windows release zips keep the tested plugin package directory:

```text
misc/
  manifest.vs
  miscfilters.dll
  LICENSE
  ...runtime DLLs when needed
```

The manifest loads `miscfilters.dll`, while the VapourSynth namespace remains `core.misc`.

## Source build notes

This repository also keeps the upstream Meson and Visual Studio project files. The local
CI and packaging path validated here is MSYS2/UCRT64 plus the VapourSynth R77 wheel SDK.

Filter behavior reference text remains in [docs/misc.rst](docs/misc.rst).
