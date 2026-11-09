"""Account-connected actions for the Noctalia Spotify island; no shell interpolation."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from urllib.parse import quote, urlparse
import os
from pathlib import Path
import subprocess
import socket
import sys

from .common import authorized, config_dir, token_file


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=60, **kwargs).stdout


INLINE = False
MESSAGES = []


def notify(message):
    if INLINE:
        MESSAGES.append(message)
        return
    subprocess.run(["notify-send", "Spotify", message], check=False)


def spotify(*args):
    return run(["spotify_player", "--config-folder", str(config_dir() / "spotify-player"), *args])


def clean(value):
    return " ".join(str(value).split())


def rows_for(items, kind):
    rows = {}
    for index, item in enumerate(items, 1):
        item = item.get("album", item) if kind == "album" else item
        identifier = item.get("id")
        if not identifier:
            continue
        title = clean(item.get("name", "Untitled"))
        artists = ", ".join(clean(a.get("name", "")) for a in item.get("artists", []))
        detail = artists if kind == "album" else clean(item.get("type", "Device"))
        rows[f"{index}. {title}\t{detail}"] = str(identifier)
    return rows


def pick(rows, prompt):
    if not rows:
        notify("No saved albums or available devices were found.")
        return None
    # Dismiss the card before opening Noctalia's native searchable picker.
    run(["noctalia", "msg", "panel-close", "mason/spotify-island:island"])
    result = subprocess.run(
        ["noctalia", "dmenu", "--prompt", prompt], input="\n".join(rows),
        capture_output=True, text=True, check=False,
    )
    # Noctalia allows free text; only an actual returned row may trigger playback.
    return rows.get(result.stdout.rstrip("\n")) if result.returncode == 0 else None


def native_open(kind, identifier):
    if kind not in {"album", "track"} or not identifier or not re.fullmatch(r"[A-Za-z0-9]{22}", identifier):
        raise ValueError("Invalid Spotify URI")
    # Spotify itself owns routing to the selected Connect device.
    run(["busctl", "--user", "call", "org.mpris.MediaPlayer2.spotify",
         "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2", "OpenUri", "s",
         "spotify:" + kind + ":" + identifier])


def play_album(identifier):
    native_open("album", identifier)


def album_cover(album, cache):
    identifier = str(album.get("id", ""))
    if not re.fullmatch(r"[A-Za-z0-9]{22}", identifier):
        return ""
    path = cache / (identifier + ".jpg")
    if path.exists():
        return str(path)
    try:
        image_url = ""
        # The public embed response can omit covers. Reuse spotify_player's
        # already-authorized API token in memory; never pass it in argv or log it.
        account_token = token_file()
        try:
            access_token = json.loads(account_token.read_text())["access_token"]
            request = Request("https://api.spotify.com/v1/albums/" + identifier,
                              headers={"Authorization": "Bearer " + access_token})
            with urlopen(request, timeout=6) as response:
                metadata = json.loads(response.read(1024 * 1024))
            images = metadata.get("images", [])
            if images:
                image_url = min(images, key=lambda image: abs((image.get("width") or 300) - 300))["url"]
        except (OSError, ValueError, TypeError, KeyError):
            pass
        if not image_url:
            url = "https://open.spotify.com/oembed?url=" + quote("https://open.spotify.com/album/" + identifier, safe="")
            with urlopen(url, timeout=6) as response:
                metadata = json.loads(response.read(128 * 1024))
            image_url = metadata.get("thumbnail_url", "")
        parsed = urlparse(image_url)
        if parsed.scheme != "https" or parsed.hostname != "i.scdn.co":
            return ""
        with urlopen(image_url, timeout=6) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            return ""
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        return str(path)
    except (OSError, ValueError, TypeError):
        return ""


def library_snapshot():
    root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    if not authorized():
        return {"authorized": False, "albums": []}
    cache = root / "noctalia/spotify-island"
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot = cache / "library.json"
    try:
        if snapshot.exists() and time.time() - snapshot.stat().st_mtime < 600:
            cached = json.loads(snapshot.read_text())
            if all(album.get("cover") for album in cached.get("albums", [])):
                return cached
        raw = json.loads(spotify("get", "key", "user-saved-albums"))
        albums = sorted(raw, key=lambda a: a.get("added_at", 0), reverse=True)[:4]
        with ThreadPoolExecutor(max_workers=4) as pool:
            covers = list(pool.map(lambda a: album_cover(a, cache), albums))
        items = [{"id": a["id"], "name": clean(a.get("name", "Album")), "cover": cover}
                 for a, cover in zip(albums, covers)]
        result = {"authorized": True, "albums": items}
        snapshot.write_text(json.dumps(result))
        snapshot.chmod(0o600)
        return result
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError):
        return {"authorized": True, "albums": [], "error": "Library unavailable"}


def menu_items(action):
    key = {"list-albums": "user-saved-albums", "list-liked": "user-liked-tracks", "list-devices": "devices"}[action]
    raw = json.loads(spotify("get", "key", key))
    items = []
    for item in raw:
        if not item.get("id"):
            continue
        detail = ", ".join(clean(a.get("name", "")) for a in item.get("artists", []))
        if action == "list-devices":
            detail = clean(item.get("type", "Device"))
            if item.get("is_active"):
                detail += " · Active"
            if item.get("is_restricted"):
                detail += " · Spotify controls restricted"
        items.append({"id": str(item["id"]), "name": clean(item.get("name", "Untitled")),
                      "detail": detail, "restricted": bool(item.get("is_restricted"))})
    if action == "list-devices":
        playback = json.loads(spotify("get", "key", "playback"))
        current = (playback or {}).get("device") or {}
        if current.get("is_restricted") and not any(i["name"] == clean(current.get("name", "")) for i in items):
            items.insert(0, {"id": "restricted:current", "name": clean(current.get("name", "Current speaker")),
                             "detail": "Active · Spotify controls restricted", "restricted": True})
    return {"items": items}


def play_track(identifier):
    native_open("track", identifier)


def main(action, identifier=None):
    if action == "snapshot":
        return library_snapshot()
    if action not in {"play-album", "play-track"} and not authorized():
        notify("Sign in to your Spotify account to access playback and your library.")
        raise ValueError("Spotify account authorization required")
    if action in ("list-albums", "list-liked", "list-devices"):
        return menu_items(action)
    if action == "play-track":
        play_track(identifier)
    elif action == "connect-device":
        devices = json.loads(spotify("get", "key", "devices"))
        if not any(d.get("id") == identifier and not d.get("is_restricted") for d in devices):
            raise ValueError("Device unavailable")
        spotify("connect", "--id", identifier)
    elif action == "like":
        spotify("like")
        notify("Added the current Spotify track to Liked Songs.")
    elif action == "albums":
        rows = rows_for(json.loads(spotify("get", "key", "user-saved-albums")), "album")
        album = pick(rows, "Play saved album")
        if album:
            play_album(album)
    elif action == "play-album":
        play_album(identifier)
    elif action == "liked":
        run(["busctl", "--user", "call", "org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2",
             "org.mpris.MediaPlayer2", "OpenUri", "s", "spotify:collection:tracks"])
    elif action == "devices":
        run(["spotify-island", "show"])
    else:
        raise ValueError("Unknown Spotify action")


def cli():
    global INLINE
    MESSAGES.clear()
    INLINE = "--json" in sys.argv[1:]
    args = [arg for arg in sys.argv[1:] if arg != "--json"]
    try:
        if len(args) not in (1, 2):
            raise ValueError("Expected one Spotify action")
        result = main(args[0], args[1] if len(args) == 2 else None)
        if INLINE:
            print(json.dumps({"ok": True, "message": " ".join(MESSAGES), **(result or {})}))
        elif result is not None:
            print(json.dumps(result))
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as error:
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else "The request failed. Check your Spotify authorization, network, and playback device."
        if INLINE:
            print(json.dumps({"ok": False, "message": message}))
        else:
            notify(message)
        sys.exit(1)


if __name__ == "__main__":
    cli()
