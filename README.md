# Spotify Island

A standalone Noctalia plugin with a floating Spotify card, album artwork, seek
and playback controls, saved albums, Liked Songs, and Spotify Connect devices.
Derived from notoxus/media-island; upstream MIT attribution is preserved.

Spotify Island owns its runtime, user services and mutable Noctalia settings.
It does not provide a NixOS or Home Manager module, and your system configuration
must not import it. Installing/updating the application does not rebuild NixOS.

## Install on NixOS

The standalone package includes Python dependencies, Soloist and a compatible
spotify_player. It uses an independent user profile, not your system flake:

```sh
nix profile install --profile "$HOME/.local/share/spotify-island/profile" github:masonjacob/spotify-island
mkdir -p "$HOME/.local/bin"
for command in spotify-island spotify-quick-control spotify-background-setup spotify-island-mpris; do
  ln -s "$HOME/.local/share/spotify-island/profile/bin/$command" "$HOME/.local/bin/$command"
done
spotify-island install
```

Keep `~/.local/bin` on the PATH inherited by Noctalia. The Nix package currently
supports x86_64 Linux. Soloist is fetched directly from Spotify, never included in
this repository or its releases. The standalone package permits this unfree
dependency; no system-wide unfree setting is needed.

To update this independent install:

```sh
nix profile upgrade --profile "$HOME/.local/share/spotify-island/profile" --all
spotify-island install
```

## Install on other Linux distributions

Requires Python 3.11+, systemd user services, Noctalia plugin API 43+, `busctl`,
`notify-send`, Spotify Soloist and `spotify_player` on PATH. Install the Python
application in an isolated environment, for example from this checkout:

```sh
python3 -m venv "$HOME/.local/share/spotify-island/venv"
"$HOME/.local/share/spotify-island/venv/bin/pip" install .
mkdir -p "$HOME/.local/bin"
for command in spotify-island spotify-quick-control spotify-background-setup spotify-island-mpris; do
  ln -s "$HOME/.local/share/spotify-island/venv/bin/$command" "$HOME/.local/bin/$command"
done
spotify-island doctor
spotify-island install
```

Python dependencies are installed from `pyproject.toml`. Native commands are
external dependencies; pip does not download or install Soloist or spotify_player.
Get Soloist from [Spotify's official downloads](https://developer.spotify.com/documentation/soloist/reference/downloads).
The account integration is tested with spotify_player 0.25.1 plus the OAuth
callback correction in `nix/spotify-player-oauth.patch`. Other distributions need
a compatible build (or apply that patch when building spotify_player). That
compatibility work is still required for a general distribution package; the
Python runtime itself does not require Nix.

## Setup

The installer copies the plugin to `~/.local/share/spotify-island/plugins/`,
registers it in Noctalia's mutable settings, adds its `spotify` widget after the
clock in bar `default`, capsule group `center`, and installs two user services:

- `spotify-island-player.service`: optional headless Soloist playback.
- `spotify-island-mpris.service`: exposes local and account playback to Noctalia.

Use `--bar NAME --group NAME` for another layout or `--no-bar` to place the widget
manually in Noctalia Settings. `--no-start` installs files without touching
services. Existing Noctalia settings are backed up and unrelated keys preserved.

Playback and account authorization are separate:

```sh
spotify-island setup                 # enter your Soloist API key, then pair in Spotify Connect
spotify-island setup --reset-key     # securely replace that key without deleting it first
spotify-island setup --account       # browser authentication for library/remote controls
```

Each person supplies their own Soloist key. Existing keys at
`~/.config/spotify-soloist/api-key` are reused without copying them into the package.
A Soloist key alone does not authorize saved albums, likes, or account controls.
The account flow uses spotify_player's existing token cache; nothing reads a
hardcoded account token filename. If the cache contains more than one token,
set `spotify_token_file` explicitly.

Optional runtime preferences in `~/.config/spotify-island/config.toml`:

```toml
# Include the terminal's flag for executing a command. No terminal is assumed.
terminal = "alacritty -e"
# Optional: select an account token if more than one exists.
# spotify_token_file = "/home/you/.cache/spotify-player/CLIENT_ID_token.json"
# soloist_command = "/path/to/soloist"
# device_name = "My music computer"
```

The card's Connect Spotify button opens account authentication in the configured
terminal. Without a terminal preference, run `spotify-island setup --account`
directly. Device name changes should be made before pairing. Avoid changing it
while a local session is active.

## Migrate from the old Home Manager module

1. Remove the spotify-island input, module import, widget and inline services from
   your Nix configuration. Build it to verify it no longer needs this repository.
2. Install this standalone application into the separate user profile above.
3. Run `spotify-island install --replace-legacy`. This explicitly disables/stops
   the old `spotify-background.service` and `spotify-soloist-mpris.service` if they
   are running, then starts the independent services. It preserves the API key.
4. Apply your updated Home Manager configuration to retire its old managed files.
   The standalone service names and mutable widget settings remain independent.

Do not run the old and new media bridges simultaneously: they use the same MPRIS
bus name to preserve compatibility with the island.

## Diagnose

```sh
spotify-island doctor
spotify-quick-control snapshot --json
systemctl --user status spotify-island-player spotify-island-mpris
journalctl --user -u spotify-island-player -u spotify-island-mpris
```

`doctor` prints paths and whether credentials are present, never their contents.
No key/account authentication is performed automatically by installation.

## Development and community submission

The canonical plugin lives in `src/spotify_island/plugins/spotify-island/` and
ships in the Python wheel. Export a submission folder with:

```sh
spotify-island export-plugin /tmp/community-submission
noctalia plugins lint /tmp/community-submission/spotify-island
```

That folder includes its own user README, MIT license and English translations.
Before a community PR, add an actual screenshot-based 960x540 `thumbnail.webp`,
follow the upstream validator and test on a clean machine. This repository's Nix
packaging is optional and is not part of the community plugin directory.

## Data and limitations

The application shells out to Soloist, spotify_player, systemctl, Noctalia and
notify-send. The plugin also invokes busctl. Local playback uses Soloist's
loopback WebSocket. Account state is polled every five seconds when local
playback is idle; account tokens may be refreshed. Artwork is downloaded from
Spotify APIs/oEmbed and the Spotify image CDN and cached locally. Credentials
remain outside the repository and Nix store, and are never part of a release.
Soloist currently accepts its API key as a process argument.

Restricted Spotify devices can expose playback but reject controls. Rate limits
and account/API access restrictions still apply. Soloist builds expire and must
be updated; see the official Spotify documentation. This update has automated
installer tests and local service smoke tests; clean non-Nix distribution,
account login and audible playback testing remain necessary before release.
