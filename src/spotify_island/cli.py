"""Install and manage Spotify Island in the user's account, independently of NixOS."""
import argparse
from datetime import datetime, timezone
import getpass
from importlib import resources
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tomllib

import tomli_w

from .common import atomic_write, config_dir, device_name, key_file, settings, soloist_command, xdg

PLUGIN_ID = "mason/spotify-island"
SERVICES = ("spotify-island-player.service", "spotify-island-mpris.service")
LEGACY_SERVICES = ("spotify-background.service", "spotify-soloist-mpris.service")


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
        (SERVICES[0], "run-player", "Spotify Island Soloist playback"),
        (SERVICES[1], "run-mpris", "Spotify Island media controls"),
    ):
        path = directory / name
        backup(path)
        atomic_write(path, f'''[Unit]
Description={description}
After=graphical-session.target
PartOf=graphical-session.target

[Service]
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
    if destination.exists():
        backup_dir = destination.with_name("plugins.backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        shutil.copytree(destination, backup_dir)
    shutil.copytree(plugin_source(), destination, dirs_exist_ok=True)
    sources.append({"name": "spotify-island", "kind": "path", "location": str(destination), "enabled": True})
    enabled = list(merged.get("plugins", {}).get("enabled", []))
    if PLUGIN_ID not in enabled:
        enabled.append(PLUGIN_ID)
    overrides.setdefault("plugins", {}).update(source=sources, enabled=enabled)
    overrides.setdefault("widget", {})["spotify"] = {
        "type": PLUGIN_ID + ":now-playing",
        "actions": {"left": "panel-toggle " + PLUGIN_ID + ":island",
                    "right": "media toggle", "middle": "panel-toggle control-center audio"},
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
        active = [name for name in LEGACY_SERVICES if subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", name], check=False).returncode == 0]
        if active and not args.replace_legacy:
            raise ValueError("Old Spotify services are active. Use --replace-legacy to stop them during migration.")
        if active:
            call("systemctl", "--user", "disable", "--now", *active)
    account_config()
    install_units(command)
    register_plugin(args.bar, args.group, not args.no_bar)
    if not args.no_start:
        call("systemctl", "--user", "daemon-reload")
        call("systemctl", "--user", "enable", SERVICES[1])
        call("systemctl", "--user", "restart", SERVICES[1])
        if key_file().is_file() and key_file().stat().st_size:
            call("systemctl", "--user", "enable", SERVICES[0])
            call("systemctl", "--user", "restart", SERVICES[0])
    print("Installed Spotify Island. No NixOS or Home Manager rebuild is required.")


def setup(reset_key=False, account=False):
    if account:
        # This config belongs to the application, never to Home Manager.
        directory = account_config()
        call("spotify_player", "--config-folder", str(directory), "authenticate")
        return
    path = key_file()
    if reset_key or not path.exists() or path.stat().st_size == 0:
        key = getpass.getpass("Spotify Soloist API key: ").strip()
        if not key:
            raise ValueError("No key supplied; the existing key was preserved")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(path, key + "\n")
    path.chmod(0o600)
    call("systemctl", "--user", "enable", SERVICES[0], SERVICES[1])
    call("systemctl", "--user", "restart", SERVICES[0], SERVICES[1])
    print("Select " + device_name() + " in Spotify Connect to pair it.")


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


def run_player():
    path = key_file()
    if not path.is_file() or not path.stat().st_size:
        print("Run spotify-island setup to enter your Soloist API key.", file=sys.stderr)
        raise SystemExit(10)
    binary = soloist_command()
    executable = shutil.which(binary)
    if not executable:
        raise ValueError("Install Spotify Soloist or set soloist_command in spotify-island/config.toml")
    device = device_name()
    os.execv(executable, [executable, "--device-name", device, "--api-key", path.read_text().strip(), "--ws", "127.0.0.1:0", "--cache-size", "512"])


def doctor():
    missing = []
    for name in ("noctalia", "busctl", "systemctl", "soloist", "spotify_player", "notify-send"):
        found = shutil.which(settings().get("soloist_command", name) if name == "soloist" else name)
        print(f"{name}: {found or 'MISSING'}")
        if not found:
            missing.append(name)
    print("Soloist key: " + ("saved" if key_file().is_file() and key_file().stat().st_size else "not configured"))
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
    setup_parser = sub.add_parser("setup", help="Enter Soloist key or authenticate Spotify account")
    setup_parser.add_argument("--reset-key", action="store_true")
    setup_parser.add_argument("--account", action="store_true")
    sub.add_parser("setup-window", help="Open account authentication using configured terminal")
    sub.add_parser("doctor", help="Check dependencies without printing credentials")
    sub.add_parser("run-player", help=argparse.SUPPRESS)
    sub.add_parser("run-mpris", help=argparse.SUPPRESS)
    export = sub.add_parser("export-plugin", help="Copy plugin directory for community submission")
    export.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "install":
            install(args)
        elif args.action == "setup":
            setup(args.reset_key, args.account)
        elif args.action == "setup-window":
            setup_window()
        elif args.action == "run-player":
            run_player()
        elif args.action == "run-mpris":
            from .mpris import cli
            cli()
        elif args.action == "doctor":
            raise SystemExit(doctor())
        elif args.action == "export-plugin":
            shutil.copytree(plugin_source() / "spotify-island", args.destination / "spotify-island")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Subprocess exception strings can contain argv; credentials must never appear here.
        print("Spotify Island: " + (str(error) if isinstance(error, ValueError) else type(error).__name__) + ". Run spotify-island doctor.", file=sys.stderr)
        raise SystemExit(1) from None


def setup_main():
    parser = argparse.ArgumentParser(description="Configure Spotify Soloist playback")
    parser.add_argument("--reset-key", action="store_true")
    args = parser.parse_args()
    try:
        setup(args.reset_key)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Setup failed. Run spotify-island doctor.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
