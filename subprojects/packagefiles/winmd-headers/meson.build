# The NuGet package has no build system of its own: winmd_reader.h sits at its
# root and includes the rest of the library relatively, so the root is all that
# has to be on the include path.
project(
  'winmd-headers',
  version: '1.0.260529.3',
  license: 'MIT',
  meson_version: '>=1.0.0',
)

winmd_headers_dep = declare_dependency(
  include_directories: include_directories('.'),
)

meson.override_dependency('winmd-headers', winmd_headers_dep)
