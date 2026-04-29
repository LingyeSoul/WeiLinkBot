"""WeiLinkBot — AI Chatbot Platform powered by WeChat iLink Bot SDK."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("weilinkbot")
except PackageNotFoundError:
    # Development mode: read directly from pyproject.toml
    import tomllib
    from pathlib import Path

    _pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if _pyproject.exists():
        with open(_pyproject, "rb") as f:
            __version__ = tomllib.load(f)["project"]["version"]
    else:
        __version__ = "0.0.0"
