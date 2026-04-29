#!/usr/bin/env python3
"""
Nuitka build script for WeiLinkBot.

Compiles the project into a single portable .exe file.
Users can double-click the exe to start the web dashboard.

Usage:
    python build.py
"""

import subprocess
import sys
import tomllib
from pathlib import Path

# ── Version (single source: pyproject.toml) ─────────────────────────

def _read_version() -> str:
    pyproject = Path(__file__).parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        return tomllib.load(f)["project"]["version"]

VERSION = _read_version()

# ── App Info (Windows exe metadata) ─────────────────────────────────

APP_NAME        = "WeiLinkBot"
PRODUCT_NAME    = "WeiLinkBot"
COMPANY_NAME    = "LingyeSoul"
FILE_VERSION    = VERSION
PRODUCT_VERSION = VERSION
FILE_DESCRIPTION = "WeiLinkBot — AI Chatbot Platform powered by WeChat iLink Bot SDK"
COPYRIGHT       = "Copyright (C) 2026 LingyeSoul"

# ── Paths ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
ENTRY_POINT = PROJECT_ROOT / "weilinkbot" / "cli" / "main.py"
ICON_PATH = PROJECT_ROOT / "static" / "icons" / "logo.ico"
DIST_DIR = PROJECT_ROOT / "dist"
OUTPUT_EXE = DIST_DIR / f"{APP_NAME}.exe"

FRONTEND_TEMPLATES = PROJECT_ROOT / "weilinkbot" / "frontend" / "templates"
FRONTEND_STATIC = PROJECT_ROOT / "weilinkbot" / "frontend" / "static"


def check_prerequisites():
    """Verify that required tools and files are present."""
    errors = []

    if sys.version_info < (3, 10):
        errors.append(f"Python >= 3.10 required, got {sys.version}")

    try:
        import nuitka  # noqa: F401
    except ImportError:
        errors.append("Nuitka not installed. Run: pip install nuitka")

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


def build():
    """Run Nuitka compilation."""
    cmd = [
        sys.executable, "-m", "nuitka",

        # ── Output ───────────────────────────────────────────────
        "--standalone",
        "--onefile",
        f"--output-filename=WeiLinkBot.exe",
        f"--output-dir={DIST_DIR}",

        # ── Icon (Windows .exe) ──────────────────────────────────
        f"--windows-icon-from-ico={ICON_PATH}",

        # ── Windows exe metadata ─────────────────────────────────
        f"--windows-company-name={COMPANY_NAME}",
        f"--windows-product-name={PRODUCT_NAME}",
        f"--windows-file-version={FILE_VERSION}",
        f"--windows-product-version={PRODUCT_VERSION}",
        f"--windows-file-description={FILE_DESCRIPTION}",
        f"--copyright={COPYRIGHT}",

        # ── Performance ──────────────────────────────────────────
        "--assume-yes-for-downloads",
        "--mingw64",

        # ── Package data (templates + static assets) ─────────────
        f"--include-package=weilinkbot",
        f"--include-package-data=weilinkbot",

        # ── Only follow project package imports ────────────────
        "--follow-import-to=weilinkbot",

        # ── Entry point ──────────────────────────────────────────
        str(ENTRY_POINT),
    ]

    print("=" * 60)
    print(f"  Building {APP_NAME} v{PRODUCT_VERSION} with Nuitka")
    print("=" * 60)
    print()
    print(f"  Product     : {PRODUCT_NAME}")
    print(f"  Company     : {COMPANY_NAME}")
    print(f"  Version     : {FILE_VERSION}")
    print(f"  Copyright   : {COPYRIGHT}")
    print(f"  Entry point : {ENTRY_POINT}")
    print(f"  Icon        : {ICON_PATH}")
    print(f"  Output      : {OUTPUT_EXE}")
    print()
    print("  This will take several minutes on the first run ...")
    print("=" * 60)
    print()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    if result.returncode != 0:
        print()
        print("[FAILED] Build exited with code", result.returncode)
        sys.exit(result.returncode)

    if OUTPUT_EXE.exists():
        size_mb = OUTPUT_EXE.stat().st_size / (1024 * 1024)
        print()
        print("=" * 60)
        print(f"  Build succeeded!")
        print(f"  Output: {OUTPUT_EXE}  ({size_mb:.1f} MB)")
        print("=" * 60)
    else:
        print(f"[WARNING] Build finished but exe not found at {OUTPUT_EXE}")


if __name__ == "__main__":
    check_prerequisites()
    build()
