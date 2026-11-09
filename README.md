# Spotify Island

A standalone Noctalia island that controls the official Spotify desktop app.
Spotify handles playback on its currently selected Connect device: your computer,
phone, Sonos speaker, or another device supported by the Spotify app. The island
runs no audio engine and never automatically transfers playback to the computer.

## How it works

```
Island buttons → Linux MPRIS → official Spotify desktop → selected Connect device
```

The desktop app must be running and signed in. Play/pause, skip and seek go to
its `org.mpris.MediaPlayer2.spotify` session. Album/track selections are passed
to the app with `OpenUri`. Whether a particular remote-device operation is
exposed through Linux MPRIS must be verified with that device; the fact that it
works in Spotify's app does not guarantee every MPRIS method works remotely.

Saved albums, Liked Songs, likes and the optional API device list use a separate
Spotify account login through spotify_player. Basic playback controls do not
require API credentials. The cast/Devices button opens the official app so you
can use its complete Connect picker, including devices absent from the public
Web API. Sonos devices marked `is_restricted` cannot receive public Web API
commands; the native-client path is deliberately separate from that API.

There is no Soloist dependency, API key, WebSocket player or custom MPRIS bridge.
No NixOS or Home Manager module is provided. The application's own installer
manages its runtime, user service and mutable Noctalia settings.

## Install on NixOS

Use a separate user profile; do not import this repository into your system flake:

```sh
nix profile install --profile "$HOME/.local/share/spotify-island/profile" github:masonjacob/spotify-island
mkdir -p "$HOME/.local/bin"
for command in spotify-island spotify-quick-control; do
  ln -s "$HOME/.local/share/spotify-island/profile/bin/$command" "$HOME/.local/bin/$command"
done
spotify-island install
```

Keep `~/.local/bin` on Noctalia's PATH. The x86_64 Linux package supplies Spotify,
a compatible spotify_player, Python and native command dependencies. It permits
the unfree Spotify desktop dependency locally; no global Nix setting is needed.
System rebuilds do not fetch or evaluate this application.

```sh
nix profile upgrade --profile "$HOME/.local/share/spotify-island/profile" --all
spotify-island install
```

## Install on other Linux distributions

Requires Python 3.11+, systemd user services, Noctalia API 43+, `busctl`,
`notify-send` and the official Spotify desktop client. Install from a checkout:

```sh
python3 -m venv "$HOME/.local/share/spotify-island/venv"
"$HOME/.local/share/spotify-island/venv/bin/pip" install .
mkdir -p "$HOME/.local/bin"
for command in spotify-island spotify-quick-control; do
  ln -s "$HOME/.local/share/spotify-island/venv/bin/$command" "$HOME/.local/bin/$command"
done
spotify-island install
```

For optional library/account features, install spotify_player on PATH too.
It is tested at 0.25.1 with the OAuth callback correction in
`nix/spotify-player-oauth.patch`; other distributions need a compatible build.
Pip installs the Python dependencies, not native applications.

## Setup and daily use

The installer copies the plugin to `~/.local/share/spotify-island/plugins/`,
registers it in Noctalia's mutable settings, adds its `spotify` widget after the
clock in bar `default`, group `center`, and enables
`spotify-island-desktop.service`. It backs up existing settings and preserves
unrelated keys. Use `--bar NAME --group NAME`, `--no-bar` for manual placement,
or `--no-start` to write files without controlling services.

The service reuses an existing Spotify session. When Spotify is absent, it starts
the app. On Hyprland a per-launch workspace rule places a new window silently on
`special:spotify-island`; it does not modify compositor or Nix configuration.
On other compositors, configure minimization through that compositor. Spotify's
`--minimized` flag only works on Windows, so it is not used here.

```sh
spotify-island show      # sign in or choose your Sonos/other Connect device
spotify-island hide      # return Spotify to the hidden Hyprland workspace
spotify-island doctor
```

The service keeps Spotify available during the graphical session. Stopping the
watcher does not terminate an app session that was already running. No playback
or device transfer is triggered by startup or installation.

Optional saved-album/like account authorization:

```sh
spotify-island setup
```

The card's Connect Spotify button opens this account flow in your configured
terminal. This is separate from logging into the desktop app. Runtime preferences
in `~/.config/spotify-island/config.toml`:

```toml
terminal = "alacritty -e"
# spotify_command = ["spotify"]
# spotify_token_file = "/home/you/.cache/spotify-player/CLIENT_ID_token.json"
```

The account helper reuses an unambiguous spotify_player token cache, or the
explicit file above. Tokens and desktop login sessions never enter this repository
or a release. A developer-owned direct OAuth client is not implemented yet.

## Migrate from an earlier version

Remove the old plugin input, Home Manager import and inline Spotify services from
your system configuration. Install this application separately, then run:

```sh
spotify-island install --replace-legacy
```

This explicitly retires `spotify-background.service`, `spotify-soloist-mpris.service`,
`spotify-island-player.service` and `spotify-island-mpris.service` if active.
Old Soloist keys/session files are preserved but are no longer read. The new
application-owned service survives removal of the old Home Manager definitions.

## Diagnose and develop

```sh
systemctl --user status spotify-island-desktop
journalctl --user -u spotify-island-desktop
spotify-quick-control snapshot --json
spotify-island export-plugin /tmp/community-submission
noctalia plugins lint /tmp/community-submission/spotify-island
```

The canonical plugin is `src/spotify_island/plugins/spotify-island/` and is included
in the Python wheel. It has its own README, MIT license and English translations.
Before submitting to community-plugins, add an actual screenshot-based 960x540
`thumbnail.webp`, run upstream validation and test Sonos remote control explicitly.

The plugin and helpers invoke Noctalia, busctl, Spotify, systemctl, notify-send,
optional spotify_player, and Hyprland's CLI where available. Artwork is downloaded
and cached; optional library operations contact Spotify APIs and cache snapshots.
The installer writes user units, plugin files and mutable settings with backups.
No unreviewed remote code is downloaded/executed by the running plugin.

Installer and routing tests cover settings preservation and directing media URIs
to the official app. They do not establish that Sonos hardware accepts the native
client's remote commands; test play/pause, skip and seek with Sonos selected.
