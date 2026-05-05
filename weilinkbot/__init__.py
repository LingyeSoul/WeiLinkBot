"""WeiLinkBot — AI Chatbot Platform powered by WeChat iLink Bot SDK."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("weilinkbot")
except PackageNotFoundError:
    from pathlib import Path

    # PyInstaller bundle: read the VERSION file placed next to _internal/
    _version_file = Path(__file__).resolve().parent.parent / "VERSION"
    if _version_file.exists():
        __version__ = _version_file.read_text(encoding="utf-8").strip()
    else:
        # Development mode: read directly from pyproject.toml
        import tomllib

        _pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        if _pyproject.exists():
            with open(_pyproject, "rb") as f:
                __version__ = tomllib.load(f)["project"]["version"]
        else:
            __version__ = "0.0.0"
