"""Set the app version everywhere it is written, or check that the copies agree.

Usage:
    python scripts/bump_version.py 0.2.0     # rewrite all copies
    python scripts/bump_version.py --check   # print them; exit 1 if they differ

Copies: pyproject.toml, src/secretary/__init__.py, packaging/version_info.txt (the file
and product versions), and the default in packaging/installer.iss (the release workflow
overrides that one with /DMyAppVersion, but the default should not lie).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _one(pattern: str, text: str, where: str) -> re.Match[str]:
    matches = list(re.finditer(pattern, text, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(f"{where}: expected exactly one match for {pattern!r}, found {len(matches)}")
    return matches[0]


def current_versions(root: Path = ROOT) -> dict[str, str]:
    """The version written in each file, keyed by a short label."""
    pyproject = _read(root / "pyproject.toml")
    init = _read(root / "src" / "secretary" / "__init__.py")
    info = _read(root / "packaging" / "version_info.txt")
    iss = _read(root / "packaging" / "installer.iss")
    filevers = _one(r"filevers=\((\d+), (\d+), (\d+), 0\)", info, "version_info filevers")
    prodvers = _one(r"prodvers=\((\d+), (\d+), (\d+), 0\)", info, "version_info prodvers")
    return {
        "pyproject.toml": _one(r'^version = "([^"]+)"', pyproject, "pyproject").group(1),
        "__init__.py": _one(r'^__version__ = "([^"]+)"', init, "__init__").group(1),
        "version_info filevers": ".".join(filevers.groups()),
        "version_info prodvers": ".".join(prodvers.groups()),
        "version_info FileVersion": _one(r"u'FileVersion', u'([^']+)'", info, "FileVersion").group(1),
        "version_info ProductVersion": _one(r"u'ProductVersion', u'([^']+)'", info, "ProductVersion").group(1),
        "installer.iss default": _one(r'#define MyAppVersion "([^"]+)"', iss, "installer.iss").group(1),
    }


def set_version(version: str, root: Path = ROOT) -> None:
    """Rewrite every copy of the version. Raises ``ValueError`` for anything but MAJOR.MINOR.PATCH."""
    if not _SEMVER.match(version):
        raise ValueError(f"version must look like 1.2.3, got {version!r}")
    major, minor, patch = version.split(".")
    tuple_text = f"({major}, {minor}, {patch}, 0)"

    path = root / "pyproject.toml"
    text = _read(path)
    _one(r'^version = "[^"]+"', text, "pyproject")
    _write(path, re.sub(r'^version = "[^"]+"', f'version = "{version}"', text, count=1, flags=re.MULTILINE))

    path = root / "src" / "secretary" / "__init__.py"
    text = _read(path)
    _one(r'^__version__ = "[^"]+"', text, "__init__")
    _write(path, re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{version}"', text, count=1, flags=re.MULTILINE))

    path = root / "packaging" / "version_info.txt"
    text = _read(path)
    for key in ("filevers", "prodvers"):
        text = re.sub(rf"{key}=\(\d+, \d+, \d+, 0\)", f"{key}={tuple_text}", text, count=1)
    for key in ("FileVersion", "ProductVersion"):
        text = re.sub(rf"(u'{key}', u')[^']+(')", rf"\g<1>{version}\g<2>", text, count=1)
    _write(path, text)

    path = root / "packaging" / "installer.iss"
    text = _read(path)
    _write(path, re.sub(r'(#define MyAppVersion ")[^"]+(")', rf"\g<1>{version}\g<2>", text, count=1))


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        sys.stdout.write(__doc__ or "")
        return 2
    if argv[1] == "--check":
        versions = current_versions()
        for label, value in versions.items():
            sys.stdout.write(f"{label}: {value}\n")
        return 0 if len(set(versions.values())) == 1 else 1
    try:
        set_version(argv[1])
    except ValueError as exc:
        sys.stdout.write(f"{exc}\n")
        return 2
    versions = current_versions()
    for label, value in versions.items():
        sys.stdout.write(f"{label}: {value}\n")
    return 0 if len(set(versions.values())) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
