# Spotify Island

Derived from notoxus/media-island 1.0.2, MIT licensed, from
https://github.com/noctalia-dev/community-plugins at revision
20986894d051af7bc0bdab85ff87442839440523 (plugins/media-island).

Local changes: persistent idle/paused bar entry, larger popup, saved-album and
Spotify Connect pickers, Like and Liked Songs actions, output-device shortcut,
click-outside dismissal, and searchable Albums/Liked Songs/Devices views inside
the island with inline action feedback. Playback controls now target the official Spotify desktop client's MPRIS session.
Optional library/account authentication is handled by spotify_player. The
standalone Python application owns background startup and user services.
No credentials belong in this directory.
