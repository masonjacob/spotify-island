# Spotify Island

Spotify artwork and playback in a compact bar widget and floating card, with
saved albums, Liked Songs and Connect device selection.

## Plugin

| Field | Value |
| --- | --- |
| ID | `mason/spotify-island` |
| Entries | Bar widget: `now-playing`; panel: `island`; service: `media-state` |

## Requirements

Install the standalone [Spotify Island helpers](https://github.com/masonjacob/spotify-island)
first. Required external commands are `busctl`, `spotify-quick-control` and
`spotify-island`. The helpers manage Soloist playback and a media bridge, and use
spotify_player for account actions. Installation instructions cover NixOS and a
Python virtual environment. Local playback requires your own Soloist API key;
library/remote features require separate Spotify account authorization.

## Usage

The standalone installer can register the plugin and add its bar widget for you:

```sh
spotify-island install
```

Alternatively enable `mason/spotify-island` in Noctalia Plugins, then add its
`now-playing` widget to your bar. The `media-state` service runs while enabled.
Click the bar item to open the card, or run:

```sh
noctalia msg panel-toggle mason/spotify-island:island
```

Use the card for playback, seeking, Like, Albums, Liked Songs, Devices and system
audio outputs. An idle Music button stays visible before playback starts.

```sh
spotify-island setup
spotify-island setup --account
spotify-island setup --reset-key
```

Configure your preferred terminal in `spotify-island/config.toml` for the card's
Connect Spotify button. The button opens account authentication; it does not
replace the Soloist key. CLI setup works without a terminal preference.

## Settings

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `auto_show` | bool | false | Open the card when playback starts or the track changes. |
| `title_limit` | int | 30 | Maximum bar title characters, between 10 and 60. |
| `click_action` | string | island | `island` opens the card; `panel` opens Noctalia's media panel. |
| `audio_visualizer` | bool | false | Enable the plugin's audio spectrum integration when available. |

## IPC

Open a specific card page:

```sh
noctalia msg plugin mason/spotify-island:island all page albums
noctalia msg plugin mason/spotify-island:island all page liked
noctalia msg plugin mason/spotify-island:island all page devices
```

## Notes

The widget targets the `org.mpris.MediaPlayer2.spotify_soloist` media bridge.
Commands run through the standalone helpers; seek requests also invoke busctl.
Artwork is downloaded and cached in plugin data; helpers cache library and album
artwork. Account actions contact Spotify APIs and may refresh stored tokens.
The API key, account tokens and Soloist sessions are kept outside the plugin.
The helpers' README lists service names, paths, installation and account limits.
Restricted devices may display playback while disabling unsupported controls.
Derived from notoxus/media-island; see LICENSE and UPSTREAM.md.
