# Noctalia Spotify Island

Standalone development snapshot extracted from masonjacob/nix-config.

## Architecture

- `plugins/spotify-island`: Luau bar widget, floating panel, polling service,
  optional visualizer, translations and plugin manifest (API 43).
- `runtime/spotify-quick-control.py`: JSON command interface for albums, liked
  songs, device selection and playback; uses spotify_player and Soloist.
- `runtime/spotify-soloist-mpris.py`: publishes playback through MPRIS for Noctalia.
- `runtime/spotify-soloist.nix`: pinned x86_64 Linux Soloist binary packaging.
- `runtime/spotify-player-oauth.patch`: spotify_player callback compatibility.
- `nix/home-manager.nix`: optional module installing helpers and user services.

The current plugin ID remains `mason/spotify-island` for compatibility.
The MIT upstream attribution is preserved in LICENSE and plugin UPSTREAM.md.
Soloist is an external unfree dependency, downloaded by Nix; it is not vendored.

## Home Manager installation

Add `github:masonjacob/spotify-island` as a flake input and import
`inputs.spotify-island.homeManagerModules.default` into Home Manager.
Set `programs.spotify-island.enable = true` and enable Noctalia's systemd service.
Nixpkgs must permit the unfree Soloist package.
Add `spotify` to your chosen bar capsule group's `members` list.
This module intentionally leaves bar layout to the consuming configuration.

Run `spotify-background-setup` in a terminal to save your Soloist API key.
Then pair the Noctalia device from Spotify Connect. Account/library actions use
spotify_player's separate authentication. Never commit API keys or token caches.

## Development

Point a Noctalia path plugin source at this checkout's `plugins` directory.
Install the runtime helpers through the module. Validate with:

```sh
noctalia plugins lint plugins/spotify-island
nix-instantiate --parse nix/home-manager.nix >/dev/null
```

## Extraction status

The original desktop configuration has not been switched to this repository.
Before release, evaluate/build the module against the consuming flake and test
playback, idle bar entry, library actions, setup, and service restart on a desktop.
The popup currently assumes Alacritty for setup, and account token lookup uses
spotify_player's current client identifier. These should become configurable.
The upstream notes describe the original spotify_player authentication design;
Soloist now owns playback and has its own API key.

Use version tags for releases and pin the input in the consuming flake.lock.
Do not install both the extracted module and the old inline runtime definitions.
