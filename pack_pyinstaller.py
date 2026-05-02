#!/usr/bin/env python3
r"""
PyInstaller pack script for WeiLinkBot.

Creates an onedir executable distribution and a versioned zip archive using the
project-local virtual environment.

Usage:
    .venv\Scripts\python.exe pack_pyinstaller.py
"""

import subprocess
import sys
import tomllib
import zipfile
from importlib.util import find_spec
from pathlib import Path


def _read_version() -> str:
    pyproject = Path(__file__).parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        return tomllib.load(f)["project"]["version"]


VERSION = _read_version()

APP_NAME = "WeiLinkBot"
APP_DIR_NAME = f"{APP_NAME}-V{VERSION}"
CONTENTS_DIR_NAME = "_internal"
ZIP_NAME = f"{APP_DIR_NAME}.zip"

PROJECT_ROOT = Path(__file__).parent
ENTRY_POINT = PROJECT_ROOT / "weilinkbot" / "cli" / "main.py"
ICON_PATH = PROJECT_ROOT / "static" / "icons" / "logo.ico"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build" / "pyinstaller"
SPEC_DIR = PROJECT_ROOT / "build" / "pyinstaller-spec"
FRONTEND_TEMPLATES = PROJECT_ROOT / "weilinkbot" / "frontend" / "templates"
FRONTEND_STATIC = PROJECT_ROOT / "weilinkbot" / "frontend" / "static"


def check_environment() -> None:
    """Fail fast if this script is not running inside the project .venv."""
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    actual = Path(sys.executable).resolve()
    expected = venv_python.resolve()
    if actual != expected:
        print()
        print("=" * 60)
        print("  [ERROR] pack_pyinstaller.py must use .venv\\Scripts\\python.exe")
        print("=" * 60)
        print()
        print(f"  Detected : {actual}")
        print(f"  Expected : {expected}")
        print()
        print("  Run from the project root:")
        print(r"    .venv\Scripts\python.exe pack_pyinstaller.py")
        print()
        print("  Or use pack_pyinstaller.bat if available.")
        print("=" * 60)
        print()
        sys.exit(1)


def check_prerequisites() -> None:
    """Verify that PyInstaller and required project files are present."""
    check_environment()
    errors: list[str] = []

    if sys.version_info < (3, 10):
        errors.append(f"Python >= 3.10 required, got {sys.version}")

    if find_spec("PyInstaller") is None:
        errors.append("PyInstaller not installed. Run: .venv\\Scripts\\python.exe -m pip install .[packaging]")

    if not ENTRY_POINT.exists():
        errors.append(f"Entry point not found: {ENTRY_POINT}")

    if not ICON_PATH.exists():
        errors.append(f"Icon not found: {ICON_PATH}")

    if not FRONTEND_TEMPLATES.exists():
        errors.append(f"Templates directory not found: {FRONTEND_TEMPLATES}")

    if not FRONTEND_STATIC.exists():
        errors.append(f"Static directory not found: {FRONTEND_STATIC}")

    if errors:
        for err in errors:
            print(f"[ERROR] {err}")
        sys.exit(1)


def build() -> None:
    """Run PyInstaller in onedir mode and zip the output directory."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)

    separator = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onedir",
        f"--name={APP_NAME}",
        f"--contents-directory={CONTENTS_DIR_NAME}",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={SPEC_DIR}",
        f"--icon={ICON_PATH}",
        f"--add-data={FRONTEND_TEMPLATES}{separator}weilinkbot/frontend/templates",
        f"--add-data={FRONTEND_STATIC}{separator}weilinkbot/frontend/static",
        "--hidden-import=aiosqlite",
        "--hidden-import=sqlalchemy.dialects.sqlite.aiosqlite",
        "--hidden-import=chromadb.telemetry.product.posthog",
        "--hidden-import=chromadb_rust_bindings",
        "--collect-all=chromadb",
        "--collect-all=chromadb_rust_bindings",
        "--collect-data=weilinkbot",
        str(ENTRY_POINT),
    ]

    print("=" * 60)
    print(f"  Building {APP_NAME} v{VERSION} with PyInstaller")
    print("=" * 60)
    print()
    print(f"  Mode        : onedir")
    print(f"  Entry point : {ENTRY_POINT}")
    print(f"  Icon        : {ICON_PATH}")
    print(f"  App exe     : {DIST_DIR / APP_NAME / (APP_NAME + '.exe')}")
    print(f"  App data    : {DIST_DIR / APP_NAME / CONTENTS_DIR_NAME}")
    print(f"  Zip output  : {DIST_DIR / ZIP_NAME}")
    print("=" * 60)
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print()
        print("[FAILED] PyInstaller exited with code", result.returncode)
        sys.exit(result.returncode)

    output_dir = DIST_DIR / APP_NAME
    output_exe = output_dir / f"{APP_NAME}.exe"
    if output_dir.exists() and output_exe.exists():
        zip_path = create_zip(output_dir)
        dir_size_mb = directory_size(output_dir) / (1024 * 1024)
        zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
        print()
        print("=" * 60)
        print("  Build succeeded!")
        print(f"  Output dir: {output_dir} ({dir_size_mb:.1f} MB)")
        print(f"  Zip file  : {zip_path} ({zip_size_mb:.1f} MB)")
        print("=" * 60)
    else:
        print(f"[WARNING] Build finished but output exe not found at {output_exe}")


def directory_size(path: Path) -> int:
    """Return total file size for a directory tree."""
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def create_zip(source_dir: Path) -> Path:
    """Create a versioned zip archive from the PyInstaller onedir output."""
    zip_path = DIST_DIR / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()

    print()
    print(f"[pack] Creating zip archive: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(source_dir.rglob("*")):
            if not file.is_file():
                continue
            archive.write(file, file.relative_to(DIST_DIR))
    return zip_path


if __name__ == "__main__":
    check_prerequisites()
    build()
