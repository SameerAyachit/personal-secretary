"""PyInstaller entry point.

``src/secretary/__main__.py`` uses package-relative imports, so it cannot be the
script PyInstaller runs directly (that fails with "attempted relative import
with no known parent package"). This shim imports the package and calls main().
"""

from secretary.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
