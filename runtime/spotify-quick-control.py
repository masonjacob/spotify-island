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
    return run(["spotify_player", *args])


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


def ensure_playback_device():
    devices = json.loads(spotify("get", "key", "devices"))
    if any(d.get("is_active") for d in devices):
        return
    local_name = "Noctalia " + socket.gethostname().split(".")[0].capitalize()
    local = next((d for d in devices if d.get("name") == local_name and d.get("id")), None)
    if local:
        spotify("connect", "--id", str(local["id"]))


def play_album(identifier):
    if not identifier or not re.fullmatch(r"[A-Za-z0-9]{22}", identifier):
        raise ValueError("Invalid album ID")
    playback = json.loads(spotify("get", "key", "playback"))
    device = (playback or {}).get("device") or {}
    local_name = "Noctalia " + socket.gethostname().split(".")[0].capitalize()
    if device and device.get("name") != local_name:
        if device.get("is_restricted"):
            notify("Spotify restricts controls on “" + clean(device.get("name", "this device")) + "”. Use Spotify or Sonos to start this album there.")
            return
        spotify("playback", "start", "context", "album", "--id", identifier)
        return
    status = run(["soloist", "ctl", "status"])
    if not re.search(r"^\s*logged in:\s*yes\s*$", status, re.MULTILINE):
        name = "Noctalia " + socket.gethostname().split(".")[0].capitalize()
        notify("First select “" + name + "” in Spotify’s Connect/device picker and play a track to pair Soloist. Then try the album again.")
        return
    run(["soloist", "ctl", "activate"])
    run(["soloist", "ctl", "play", "spotify:album:" + identifier])


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
        token_file = cache.parents[1] / "spotify-player/d420a117a32841c2b3474932e49fb54b_token.json"
        try:
            access_token = json.loads(token_file.read_text())["access_token"]
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
    if not (root / "spotify-player/credentials.json").exists():
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
    if not identifier or not re.fullmatch(r"[A-Za-z0-9]{22}", identifier):
        raise ValueError("Invalid track ID")
    playback = json.loads(spotify("get", "key", "playback"))
    device = (playback or {}).get("device") or {}
    local_name = "Noctalia " + socket.gethostname().split(".")[0].capitalize()
    if device and device.get("name") != local_name:
        if device.get("is_restricted"):
            notify("Spotify restricts playback on “" + clean(device.get("name", "this speaker")) +
                   "”. Choose another device here, or start playback in Spotify/Sonos.")
            return
        spotify("playback", "start", "track", "--id", identifier)
        return
    status = run(["soloist", "ctl", "status"])
    if not re.search(r"^\s*logged in:\s*yes\s*$", status, re.MULTILINE):
        notify("First select “" + local_name + "” in Spotify’s device picker and play a track to pair it.")
        return
    run(["soloist", "ctl", "activate"])
    run(["soloist", "ctl", "play", "spotify:track:" + identifier])


def main(action, identifier=None):
    if action == "snapshot":
        print(json.dumps(library_snapshot()))
        return
    credentials = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "spotify-player/credentials.json"
    if action != "play-album" and not credentials.exists():
        notify("Your Spotify library needs API authorization; playback uses Soloist independently.")
        return
    run(["systemctl", "--user", "start", "spotify-background.service"])
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
        playback = json.loads(spotify("get", "key", "playback"))
        device = (playback or {}).get("device") or {}
        if device.get("is_restricted"):
            notify("Spotify restricts playback on “" + clean(device.get("name", "this speaker")) +
                   "”. Choose another device, or start playback in Spotify/Sonos.")
            return
        ensure_playback_device()
        spotify("playback", "start", "liked")
    elif action == "devices":
        devices = json.loads(spotify("get", "key", "devices"))
        rows = rows_for([d for d in devices if not d.get("is_restricted")], "device")
        playback = json.loads(spotify("get", "key", "playback"))
        current = (playback or {}).get("device") or {}
        if current.get("is_restricted"):
            rows[clean(current.get("name", "Current speaker")) + "\tPlaying device · Spotify API restricted"] = "restricted:current"
        device = pick(rows, "Spotify devices (some speakers require Sonos)")
        if device == "restricted:current":
            notify("Spotify reports this speaker as restricted and provides no controllable device ID. Use Spotify/Sonos, or a direct Sonos connection on the same network.")
        elif device:
            spotify("connect", "--id", device)
    else:
        raise ValueError("Unknown Spotify action")


if __name__ == "__main__":
    INLINE = "--json" in sys.argv[1:]
    args = [arg for arg in sys.argv[1:] if arg != "--json"]
    try:
        if len(args) not in (1, 2):
            raise ValueError("Expected one Spotify action")
        result = main(args[0], args[1] if len(args) == 2 else None)
        if INLINE:
            print(json.dumps({"ok": True, "message": " ".join(MESSAGES), **(result or {})}))
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError):
        message = "The request failed. Check your Spotify authorization, network, and playback device."
        if INLINE:
            print(json.dumps({"ok": False, "message": message}))
        else:
            notify(message)
        sys.exit(1)
