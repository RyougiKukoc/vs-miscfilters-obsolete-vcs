project('Miscfilters', 'cpp',
  default_options: ['buildtype=release', 'warning_level=2', 'b_ndebug=if-release', 'cpp_std=c++14'],
  meson_version : '>=0.48.0',
  version : '2.0'
)

plugin_name = 'miscfilters'

sources = [
  'src/miscfilters.cpp'
]

vapoursynth_dep = dependency('vapoursynth', version: '>=55').partial_dependency(compile_args : true, includes : true)

shared_module(plugin_name, sources,
  dependencies : vapoursynth_dep,
  name_prefix : '',
  install : true,
  install_dir : join_paths(vapoursynth_dep.get_pkgconfig_variable('libdir'), 'plugins', 'misc'),
  gnu_symbol_visibility : 'hidden'
)
