"""Install and manage Spotify Island in the user's account, independently of NixOS."""
import argparse
from datetime import datetime, timezone
from importlib import resources
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time
import tempfile
import tomllib

import tomli_w

from .common import atomic_write, config_dir, settings, xdg

PLUGIN_ID = "mason/spotify-island"
SERVICES = ("spotify-island-desktop.service",)
LEGACY_SERVICES = ("spotify-background.service", "spotify-soloist-mpris.service", "spotify-island-player.service", "spotify-island-mpris.service")


def call(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def backup(path):
    if path.exists() or path.is_symlink():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = path.with_name(path.name + ".backup-" + stamp)
        shutil.copy2(path, target)
        return target


def systemd_quote(value):
    # ExecStart uses systemd quoting, not a shell. Escape specifiers too.
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def install_units(command):
    directory = xdg("XDG_CONFIG_HOME", ".config") / "systemd/user"
    for name, action, description in (
        (SERVICES[0], "run-desktop", "Spotify desktop controller for Spotify Island"),
    ):
        path = directory / name
        backup(path)
        atomic_write(path, f'''[Unit]
Description={description}
After=graphical-session.target
PartOf=graphical-session.target

[Service]
EnvironmentFile=-%t/uwsm/env_session.conf
ExecStart={systemd_quote(command)} {action}
Restart=on-failure
RestartSec=5
RestartPreventExitStatus=10
UMask=0077

[Install]
WantedBy=graphical-session.target
''', 0o644)


def plugin_source():
    return Path(str(resources.files("spotify_island") / "plugins"))


def register_plugin(bar="default", group="center", add_bar=True):
    # Use the merged base to preserve every unrelated plugin and bar widget.
    result = call("noctalia", "config", "export", "merged", capture_output=True, text=True)
    merged = tomllib.loads(result.stdout)
    path = xdg("XDG_STATE_HOME", ".local/state") / "noctalia/settings.toml"
    overrides = tomllib.loads(path.read_text()) if path.exists() else {}
    sources = list(merged.get("plugins", {}).get("source", []))
    sources = [source for source in sources if source.get("name") != "spotify-island"]
    destination = xdg("XDG_DATA_HOME", ".local/share") / "spotify-island/plugins"
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".plugins-", dir=destination.parent))
    previous = None
    try:
        shutil.copytree(plugin_source(), staging, dirs_exist_ok=True)
        for item in [staging, *staging.rglob("*")]:
            item.chmod(0o755 if item.is_dir() else 0o644)
        if destination.exists():
            previous = destination.with_name("plugins.backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            destination.rename(previous)
        try:
            staging.rename(destination)
        except OSError:
            if previous is not None:
                previous.rename(destination)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    sources.append({"name": "spotify-island", "kind": "path", "location": str(destination), "enabled": True})
    enabled = list(merged.get("plugins", {}).get("enabled", []))
    if PLUGIN_ID not in enabled:
        enabled.append(PLUGIN_ID)
    overrides.setdefault("plugins", {}).update(source=sources, enabled=enabled)
    overrides.setdefault("widget", {})["spotify"] = {
        "type": PLUGIN_ID + ":now-playing",
        "actions": {"left": "panel-toggle " + PLUGIN_ID + ":island",
                    "right": "exec noctalia msg plugin mason/spotify-island:media-state all toggle", "middle": "exec spotify-island show"},
    }
    if add_bar:
        bar_config = merged.get("bar", {}).get(bar)
        if bar_config is None:
            raise ValueError(f"No bar named {bar!r}; use --bar NAME or --no-bar")
        groups = bar_config.get("capsule_group", [])
        target = next((item for item in groups if item.get("id") == group), None)
        if target is None:
            raise ValueError(f"No capsule group named {group!r}; use --group NAME or --no-bar")
        members = target.setdefault("members", [])
        if "spotify" not in members:
            members.insert(members.index("clock") + 1 if "clock" in members else len(members), "spotify")
        overrides.setdefault("bar", {}).setdefault(bar, {})["capsule_group"] = groups
    backup(path)
    atomic_write(path, tomli_w.dumps(overrides))


def account_config():
    directory = config_dir() / "spotify-player"
    directory.mkdir(parents=True, exist_ok=True)
    app = directory / "app.toml"
    if not app.exists():
        atomic_write(app, 'enable_streaming = "Never"\nenable_media_control = false\nenable_notify = false\nlogin_redirect_uri = "http://127.0.0.1:5588/login"\n')
    return directory


def install(args):
    command = str(Path(shutil.which("spotify-island") or sys.argv[0]).absolute())
    if not args.no_start:
        active = [name for name in LEGACY_SERVICES if any(subprocess.run(
            ["systemctl", "--user", state, "--quiet", name], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False).returncode == 0
            for state in ("is-active", "is-enabled"))]
        if active and not args.replace_legacy:
            raise ValueError("Old Spotify services are active. Use --replace-legacy to stop them during migration.")
        if active:
            call("systemctl", "--user", "disable", "--now", *active)
    account_config()
    install_units(command)
    register_plugin(args.bar, args.group, not args.no_bar)
    if not args.no_start:
        call("systemctl", "--user", "daemon-reload")
        call("systemctl", "--user", "enable", SERVICES[0])
        call("systemctl", "--user", "restart", SERVICES[0])
    print("Installed Spotify Island. No NixOS or Home Manager rebuild is required.")


def setup():
    directory = account_config()
    call("spotify_player", "--config-folder", str(directory), "authenticate")
    call("systemctl", "--user", "restart", SERVICES[0])


def setup_window():
    configured = settings().get("terminal")
    if configured:
        argv = shlex.split(configured)
        if not argv:
            raise ValueError("terminal must contain a command")
    else:
        raise ValueError("Set terminal in spotify-island/config.toml, or run spotify-island setup --account in a terminal")
    command = shutil.which("spotify-island") or sys.argv[0]
    subprocess.Popen([*argv, command, "setup", "--account"], start_new_session=True)



def desktop_available():
    return subprocess.run(["busctl", "--user", "get-property", "org.mpris.MediaPlayer2.spotify",
                           "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2", "CanRaise"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def hyprland_clients():
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or not shutil.which("hyprctl"):
        return []
    result = call("hyprctl", "clients", "-j", capture_output=True, text=True)
    return [client for client in json.loads(result.stdout) if client.get("class", "").lower() == "spotify"]


def hide_desktop():
    clients = hyprland_clients()
    if not clients:
        raise ValueError("Automatic background placement currently requires Hyprland; minimize Spotify with your compositor")
    for client in clients:
        call("hyprctl", "eval", 'hl.dispatch(hl.dsp.window.move({ window = ' + json.dumps("address:" + client["address"]) + ', workspace = "special:spotify-island", follow = false }))', stdout=subprocess.DEVNULL)


def show_desktop():
    clients = hyprland_clients()
    if clients:
        workspace = json.loads(call("hyprctl", "activeworkspace", "-j", capture_output=True, text=True).stdout)["id"]
        for client in clients:
            call("hyprctl", "eval", 'hl.dispatch(hl.dsp.window.move({ window = ' + json.dumps("address:" + client["address"]) + ", workspace = " + str(workspace) + ", follow = false }))", stdout=subprocess.DEVNULL)
        call("hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ window = ' + json.dumps("address:" + clients[0]["address"]) + " }))", stdout=subprocess.DEVNULL)
    else:
        call("busctl", "--user", "call", "org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2",
             "org.mpris.MediaPlayer2", "Raise")


def run_desktop():
    command = settings().get("spotify_command", ["spotify"])
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise ValueError("spotify_command must be a nonempty array of command arguments")
    executable = shutil.which(command[0])
    if not executable:
        raise ValueError("Spotify desktop is not installed; set spotify_command to its executable")
    command = [executable, *command[1:]]
    while True:
        if not desktop_available():
            # Per-launch rule avoids changing the user's compositor/Nix configuration.
            if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
                call("hyprctl", "eval", "hl.exec_cmd(" + json.dumps(shlex.join(command), ensure_ascii=False) + ', { workspace = "special:spotify-island silent" })', stdout=subprocess.DEVNULL)
            else:
                subprocess.Popen(command)
            for _ in range(30):
                time.sleep(1)
                if desktop_available():
                    break
            else:
                raise ValueError("Spotify did not expose its media session; run spotify-island show or open Spotify to sign in")
        time.sleep(5)


def doctor():
    missing = []
    for name in ("noctalia", "busctl", "systemctl", "spotify", "notify-send"):
        found = shutil.which(name)
        print(f"{name}: {found or 'MISSING'}")
        if not found:
            missing.append(name)
    print("spotify_player (optional library features): " + (shutil.which("spotify_player") or "not installed"))
    from .common import authorized
    print("Account token: " + ("available" if authorized() else "not configured or ambiguous"))
    return int(bool(missing))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    install_parser = sub.add_parser("install", help="Install user services, plugin and bar entry")
    install_parser.add_argument("--no-start", action="store_true", help="Write files without controlling services")
    install_parser.add_argument("--replace-legacy", action="store_true", help="Stop old Home Manager Spotify services before starting standalone ones")
    install_parser.add_argument("--no-bar", action="store_true")
    install_parser.add_argument("--bar", default="default")
    install_parser.add_argument("--group", default="center")
    setup_parser = sub.add_parser("setup", help="Authenticate your Spotify account")
    setup_parser.add_argument("--account", action="store_true")
    sub.add_parser("setup-window", help="Open account authentication using configured terminal")
    sub.add_parser("doctor", help="Check dependencies without printing credentials")
    sub.add_parser("run-desktop", help="Keep the official Spotify client available in the background")
    sub.add_parser("show", help="Show Spotify to sign in or choose a Connect device")
    sub.add_parser("hide", help="Return Spotify to the background on Hyprland")
    export = sub.add_parser("export-plugin", help="Copy plugin directory for community submission")
    export.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "install":
            install(args)
        elif args.action == "setup":
            setup()
        elif args.action == "setup-window":
            setup_window()
        elif args.action == "run-desktop":
            run_desktop()
        elif args.action == "show":
            show_desktop()
        elif args.action == "hide":
            hide_desktop()
        elif args.action == "doctor":
            raise SystemExit(doctor())
        elif args.action == "export-plugin":
            shutil.copytree(plugin_source() / "spotify-island", args.destination / "spotify-island")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Subprocess exception strings can contain argv; credentials must never appear here.
        print("Spotify Island: " + (str(error) if isinstance(error, ValueError) else type(error).__name__) + ". Run spotify-island doctor.", file=sys.stderr)
        raise SystemExit(1) from None



if __name__ == "__main__":
    main()
