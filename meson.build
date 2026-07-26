project(
  'winmd',
  'cpp',
  # The version lives in pyproject.toml; nothing here needs it.
  meson_version: '>=1.0.0',
  default_options: ['cpp_std=c++17', 'b_ndebug=if-release'],
)

# The package ships an extension module, so everything goes to platlib.
python = import('python').find_installation(pure: false)

# The wrapped C++ library is not part of the repository.
fs = import('fs')
if not fs.is_file('winmd/winmd_reader.h')
  error('winmd/winmd_reader.h is missing - run "fetch-packages.ps1 -Kind library" first')
endif

# nanobind (and its robin-map dependency) come from subprojects/*.wrap, which
# were added with `meson wrap install nanobind` / `meson wrap install robin-map`.
nanobind_dep = dependency('nanobind', static: true)

cpp = meson.get_compiler('cpp')

extension_args = ['-DNOMINMAX']

if cpp.get_argument_syntax() == 'msvc'
  # winmd_reader.h pulls in <windows.h>; the templated bindings need /bigobj.
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
  # winmd_reader.h is included as "winmd/winmd_reader.h", so the repository
  # root is the include directory.
  include_directories: include_directories('.'),
  dependencies: [nanobind_dep],
  cpp_args: extension_args,
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
