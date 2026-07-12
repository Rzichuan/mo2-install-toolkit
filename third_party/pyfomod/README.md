# pyfomod 1.2.1

`pyfomod 1.2.1` is vendored under `src/mo2_agent_toolkit/_vendor/pyfomod`.

- Upstream: https://github.com/GandaG/pyfomod
- License: Apache-2.0
- Vendoring reason: the upstream package declares `lxml>=4,<5`, which is not a viable runtime dependency for the toolkit's Python 3.14/PyInstaller build. The engine itself is compatible after the local portability changes below.

Local compatibility and integration changes:

- `parser.py` uses `xml.etree.ElementTree` instead of `lxml`.
- Version comparison no longer depends on removed `distutils.version.LooseVersion`.
- The initial installer page is evaluated with the same ordering and visibility rules as later pages.
- `Installer.file_infos()` preserves duplicate source mappings and resolved priorities while the upstream `files()` API remains available.
- The toolkit supplies MO2-aware file/plugin states and performs copying, staging, transaction, and audit operations outside the vendored engine.
