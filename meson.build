project(
  'winmd',
  'cpp',
  # The version lives in pyproject.toml; nothing here needs it.
  meson_version: '>=1.3.0',  # 1.3 is what the limited_api kwarg needs
  default_options: ['cpp_std=c++17', 'b_ndebug=if-release'],
)

# The package ships an extension module, so everything goes to platlib.
python = import('python').find_installation(pure: false)

# Everything the build needs comes from subprojects/*.wrap and is downloaded on
# demand: the C++ library that is wrapped (the Microsoft.Windows.WinMD NuGet
# package) and nanobind with its robin-map dependency.
winmd_dep = dependency('winmd-headers')

# nanobind's own dependency pulls in py.dependency(), which on Windows carries
# python3XX.lib and would tie the extension to that one version however it is
# compiled. Only the headers, the sources and the compiler flags are wanted -
# extension_module() links the stable ABI python3.lib by itself. Taking the link
# arguments along would take that .lib with them, so nanobind's stripping flags
# are given up here; they only affect the size of the binary.
nanobind_dep = dependency('nanobind', static: true).partial_dependency(
  compile_args: true,
  includes: true,
  sources: true,
)

cpp = meson.get_compiler('cpp')

extension_args = []

if host_machine.system() == 'windows'
  # winmd_reader.h pulls in <windows.h> there; elsewhere it uses mmap instead.
  extension_args += ['-DNOMINMAX']
endif

if cpp.get_argument_syntax() == 'msvc'
  # The templated bindings make for one big object file.
  extension_args += ['/bigobj', '/utf-8', '/permissive-', '/D_CRT_SECURE_NO_WARNINGS']
else
  extension_args += ['-fno-strict-aliasing', '-Wno-unused-parameter']
endif

python.extension_module(
  '_winmd',
  sources: [
    'src/cache.cpp',
    'src/enums.cpp',
    'src/helpers.cpp',
    'src/indexes.cpp',
    'src/module.cpp',
    'src/rows.cpp',
    'src/signatures.cpp',
    'src/tables.cpp',
    'src/view.cpp',
  ],
  include_directories: include_directories('src'),
  dependencies: [winmd_dep, nanobind_dep],
  cpp_args: extension_args,
  # One binary for every Python from 3.12 on. That is as far back as the stable
  # ABI goes for nanobind; building for an older one means turning this off with
  # -Dpython.allow_limited_api=false, which drops the abi3 tag as well.
  limited_api: '3.12',
  subdir: 'winmd',
  install: true,
)

python.install_sources(
  [
    'python/winmd/__init__.py',
    'python/winmd/__init__.pyi',
    'python/winmd/py.typed',
  ],
  subdir: 'winmd',
)

# Stubs for the extension module itself, generated with
# `python -m nanobind.stubgen -m winmd._winmd -r -O python/winmd`.
python.install_sources(
  [
    'python/winmd/_winmd/__init__.pyi',
    'python/winmd/_winmd/reader.pyi',
  ],
  subdir: 'winmd/_winmd',
)
