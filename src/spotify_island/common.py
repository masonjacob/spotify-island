"""Paths and explicit runtime configuration; never log credentials."""
import json
import os
import socket
from pathlib import Path
import tempfile
import tomllib


def xdg(variable, default):
    return Path(os.environ.get(variable, str(Path.home() / default)))


def config_dir():
    return xdg("XDG_CONFIG_HOME", ".config") / "spotify-island"


def settings():
    path = config_dir() / "config.toml"
    return tomllib.loads(path.read_text()) if path.exists() else {}


def token_file():
    configured = settings().get("spotify_token_file")
    if configured:
        return Path(configured).expanduser()
    cache = xdg("XDG_CACHE_HOME", ".cache") / "spotify-player"
    candidates = sorted(cache.glob("*_token.json"))
    if len(candidates) != 1:
        raise OSError("Set spotify_token_file in spotify-island/config.toml when zero or multiple account tokens exist")
    return candidates[0]


def authorized():
    try:
        return bool(json.loads(token_file().read_text()).get("access_token"))
    except (OSError, ValueError):
        return False


def atomic_write(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

