"""Expose Soloist's local event stream to standard desktop media controls."""
import asyncio
import json
import os
from pathlib import Path
import re
import time
import threading
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

from dbus_next import BusType, DBusError, Variant
from dbus_next.aio import MessageBus
from dbus_next.constants import PropertyAccess
from dbus_next.service import ServiceInterface, dbus_property, method, signal
from websockets.asyncio.client import connect

from .common import token_file


class AccountAPI:
    """Account-wide state with token renewal and Retry-After backoff."""
    def __init__(self):
        self.token_file = None
        self.retry_at = 0
        self.lock = threading.Lock()

    def request(self, path, method='GET', body=None):
        with self.lock:
            if time.monotonic() < self.retry_at:
                raise OSError('Spotify account API is cooling down')
            self.token_file = token_file()
            token = json.loads(self.token_file.read_text())
            for attempt in range(2):
                request = Request('https://api.spotify.com/v1/' + path,
                                  data=json.dumps(body).encode() if body is not None else None,
                                  headers={'Authorization': 'Bearer ' + token['access_token'],
                                           'Content-Type': 'application/json'}, method=method)
                try:
                    with urlopen(request, timeout=8) as response:
                        raw = response.read(2 * 1024 * 1024)
                        return json.loads(raw) if raw else None
                except HTTPError as error:
                    if error.code == 401 and attempt == 0:
                        refresh = Request('https://accounts.spotify.com/api/token', data=urlencode({
                            'grant_type': 'refresh_token', 'refresh_token': token['refresh_token'],
                            'client_id': self.token_file.name.removesuffix('_token.json'),
                        }).encode())
                        with urlopen(refresh, timeout=8) as response:
                            token.update(json.load(response))
                        token['expires_at'] = (datetime.now(timezone.utc) + timedelta(seconds=token.get('expires_in', 3600))).isoformat()
                        temporary = self.token_file.with_suffix('.refresh.tmp')
                        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        with os.fdopen(fd, 'w') as file: json.dump(token, file)
                        os.replace(temporary, self.token_file)
                        continue
                    if error.code == 429:
                        self.retry_at = time.monotonic() + max(5, int(error.headers.get('Retry-After', '30')))
                    raise OSError('Spotify account API returned HTTP ' + str(error.code)) from None


def account_state(data):
    if not data or not data.get('item'):
        return {}
    item = data['item']
    device = data.get('device') or {}
    denied = (data.get('actions') or {}).get('disallows') or {}
    restricted = device.get('is_restricted', False)
    playing = data.get('is_playing', False)
    actions = {}
    for action, restriction in [('play', 'resuming'), ('pause', 'pausing'), ('seek', 'seeking'),
                                ('skip_next', 'skipping_next'), ('skip_prev', 'skipping_prev')]:
        if not restricted and not denied.get(restriction, False): actions[action] = {}
    album = item.get('album') or item.get('show') or {}
    return {
        'is_active': True, 'status': 'playing' if playing else 'paused',
        'available_actions': actions, 'restricted': restricted,
        'device_id': device.get('id'), 'device_name': device.get('name', ''),
        'position': {'position_ms': data.get('progress_ms') or 0,
                     'timestamp_ms': time.time() * 1000, 'speed': 1.0 if playing else 0.0},
        'volume': device.get('volume_percent') or 0,
        'item': {'uri': item.get('uri', ''), 'decorations': {
            'identity': {'name': item.get('name', '')},
            'playback': {'duration_ms': item.get('duration_ms', 0)},
            'visual_identity': {'cover': album.get('images') or item.get('images') or []},
            'parent': {'entity': {'decorations': {'identity': {'name': album.get('name', '')}}}},
            'creators': [{'entity': {'decorations': {'identity': {'name': a.get('name', '')}}}}
                         for a in item.get('artists', [{'name': album.get('publisher', '')}])],
        }},
    }


class Playback:
    def __init__(self):
        self.state = {}
        self.connected = False

    @property
    def status(self):
        if not self.connected or not self.state.get('is_active'):
            return 'Stopped'
        return {'playing': 'Playing', 'buffering': 'Paused', 'paused': 'Paused'}.get(self.state.get('status'), 'Stopped')

    @property
    def metadata(self):
        item = self.state.get('item') or {}
        uri = item.get('uri', '')
        if not uri or self.status == 'Stopped':
            return {}
        dec = item.get('decorations') or {}
        parent = (dec.get('parent') or {}).get('entity') or {}
        art = (dec.get('visual_identity') or {}).get('cover') or []
        creators = dec.get('creators') or []
        return {
            'mpris:trackid': Variant('o', '/org/mpris/MediaPlayer2/track/' + re.sub('[^A-Za-z0-9_]', '_', uri)),
            'mpris:length': Variant('x', int((dec.get('playback') or {}).get('duration_ms', 0)) * 1000),
            'xesam:url': Variant('s', uri),
            'xesam:title': Variant('s', (dec.get('identity') or {}).get('name', '')),
            'xesam:artist': Variant('as', [(c.get('entity', {}).get('decorations', {}).get('identity') or {}).get('name', '') for c in creators]),
            'xesam:album': Variant('s', (parent.get('decorations', {}).get('identity') or {}).get('name', '')),
            'mpris:artUrl': Variant('s', art[0].get('url', '') if art else ''),
        }

    @property
    def position(self):
        anchor = self.state.get('position') or {}
        pos = float(anchor.get('position_ms', 0))
        if self.status == 'Playing':
            pos += max(0, time.time() * 1000 - anchor.get('timestamp_ms', time.time() * 1000)) * anchor.get('speed', 0)
        duration = self.metadata.get('mpris:length')
        return max(0, min(int(pos * 1000), duration.value if duration else 0))


class Root(ServiceInterface):
    def __init__(self):
        super().__init__('org.mpris.MediaPlayer2')

    @method()
    def Raise(self):
        pass

    @method()
    def Quit(self):
        pass

    @dbus_property(access=PropertyAccess.READ)
    def CanQuit(self) -> 'b': return False

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> 'b': return False

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> 'b': return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> 's': return 'Spotify Account'

    @dbus_property(access=PropertyAccess.READ)
    def DesktopEntry(self) -> 's': return 'spotify'

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> 'as': return ['spotify']

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> 'as': return []


class Player(ServiceInterface):
    def __init__(self):
        super().__init__('org.mpris.MediaPlayer2.Player')
        self.local_playback = Playback()
        self.remote_playback = Playback()
        self.api = AccountAPI()
        self.socket = None
        self.refresh_account = asyncio.Event()

    @property
    def playback(self):
        if self.local_playback.status != 'Stopped':
            return self.local_playback
        return self.remote_playback

    @playback.setter
    def playback(self, value):
        self.local_playback = value

    async def command(self, command, **fields):
        if self.socket is not None and (command == 'get_state' or self.local_playback.status != 'Stopped'):
            await self.socket.send(json.dumps(dict(type='command', command=command, **fields)))
            return
        if self.remote_playback.status == 'Stopped':
            raise DBusError('org.mpris.MediaPlayer2.Error.Failed', 'No Spotify playback device is active')
        if not self.CanControl:
            raise DBusError('org.mpris.MediaPlayer2.Error.Failed', 'Spotify restricts controls on this device')
        endpoints = {'play': ('PUT', 'me/player/play'), 'pause': ('PUT', 'me/player/pause'),
                     'skip_next': ('POST', 'me/player/next'), 'skip_prev': ('POST', 'me/player/previous'),
                     'seek': ('PUT', 'me/player/seek?' + urlencode(fields))}
        if command not in endpoints:
            raise DBusError('org.mpris.MediaPlayer2.Error.NotSupported', 'Unsupported remote control')
        method, path = endpoints[command]
        # Target the observed device, rather than silently controlling a newly active one.
        identifier = self.remote_playback.state.get('device_id')
        if identifier:
            path += ('&' if '?' in path else '?') + urlencode({'device_id': identifier})
        body = {'context_uri': fields['uri']} if command == 'play' and fields.get('uri') else None
        try:
            await asyncio.to_thread(self.api.request, path, method, body)
        except OSError:
            await asyncio.create_subprocess_exec('notify-send', 'Spotify', 'Spotify rejected the remote control request. The device may be restricted or the API rate limited.')
            raise DBusError('org.mpris.MediaPlayer2.Error.Failed', 'Spotify remote control failed') from None
        self.refresh_account.set()

    async def watch_account(self):
        last_success = 0
        while True:
            try:
                if self.local_playback.status == 'Stopped':
                    data = await asyncio.to_thread(self.api.request, 'me/player')
                    self.remote_playback.state = account_state(data)
                    self.remote_playback.connected = True
                    last_success = time.monotonic()
                    self.publish()
            except (OSError, ValueError, KeyError):
                if time.monotonic() - last_success > 30:
                    self.remote_playback.connected = False
                    self.remote_playback.state = {}
                    self.publish()
            self.refresh_account.clear()
            try:
                await asyncio.wait_for(self.refresh_account.wait(), timeout=5)
            except TimeoutError:
                pass

    def publish(self):
        self.emit_properties_changed({
            'PlaybackStatus': self.PlaybackStatus, 'Metadata': self.Metadata,
            'CanPlay': self.CanPlay, 'CanPause': self.CanPause,
            'CanGoNext': self.CanGoNext, 'CanGoPrevious': self.CanGoPrevious,
            'CanSeek': self.CanSeek, 'CanControl': self.CanControl,
            'Volume': self.Volume,
        })

    def allowed(self, action):
        return self.playback.connected and self.playback.state.get('is_active', False) and action in self.playback.state.get('available_actions', {})

    @method()
    async def Next(self): await self.command('skip_next')

    @method()
    async def Previous(self): await self.command('skip_prev')

    @method()
    async def Pause(self): await self.command('pause')

    @method()
    async def Play(self): await self.command('play')

    @method()
    async def PlayPause(self): await self.command('pause' if self.PlaybackStatus == 'Playing' else 'play')

    @method()
    async def Stop(self): await self.command('pause')

    @method()
    async def Seek(self, Offset: 'x'):
        await self.command('seek', position_ms=max(0, (self.Position + Offset) // 1000))

    @method()
    async def SetPosition(self, TrackId: 'o', Position: 'x'):
        track = self.Metadata.get('mpris:trackid')
        if track and track.value == TrackId and Position >= 0:
            await self.command('seek', position_ms=Position // 1000)

    @method()
    async def OpenUri(self, Uri: 's'):
        if not re.fullmatch(r'spotify:(track|album|playlist|episode):[A-Za-z0-9]{22}', Uri):
            raise DBusError('org.mpris.MediaPlayer2.Error.InvalidUri', 'Unsupported Spotify URI')
        await self.command('play', uri=Uri)

    @signal()
    def Seeked(self, Position) -> 'x': return Position

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> 's': return self.playback.status

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> 'a{sv}': return self.playback.metadata

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> 'x': return self.playback.position

    @dbus_property(access=PropertyAccess.READ)
    def Rate(self) -> 'd': return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> 'd': return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> 'd': return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def Volume(self) -> 'd': return float(self.playback.state.get('volume', 100)) / 100

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> 'b': return bool(self.allowed('skip_next'))

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> 'b': return bool(self.allowed('skip_prev'))

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> 'b': return bool(self.allowed('play'))

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> 'b': return bool(self.allowed('pause'))

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> 'b': return bool(self.allowed('seek'))

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> 'b': return self.playback.connected and bool(self.playback.state.get('is_active')) and not self.playback.state.get('restricted', False)

    async def watch(self):
        data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'soloist'
        while True:
            try:
                port = int((data / 'ws.port').read_text().strip())
                if not 0 < port < 65536: raise ValueError('Invalid local port')
                async with connect(f'ws://127.0.0.1:{port}', open_timeout=5) as socket:
                    self.socket = socket
                    self.local_playback.connected = True
                    async for raw in socket:
                        event = json.loads(raw)
                        kind = event.get('type')
                        if kind == 'playback_state':
                            self.local_playback.state = event
                            self.publish()
                        elif kind == 'auth_state':
                            if event.get('logged_in'):
                                await self.command('get_state')
                            else:
                                self.local_playback.state = {}
                                self.publish()
                        elif kind == 'position_sync':
                            self.local_playback.state['position'] = event.get('position', {})
                            self.Seeked(self.Position)
                        elif kind in {'track_changed', 'playback_changed', 'device_changed', 'options_changed', 'volume_changed'}:
                            await self.command('get_state')
                        elif kind == 'error':
                            # Errors must not leave an optimistic playing indicator behind.
                            print('Soloist rejected a local control request', flush=True)
                            await asyncio.create_subprocess_exec('notify-send', 'Spotify', 'Soloist rejected the playback request. Check pairing and the selected device.')
            except (OSError, ValueError, TimeoutError, ConnectionError):
                pass
            except Exception as error:
                print('Soloist connection interrupted: ' + type(error).__name__, flush=True)
            finally:
                self.socket = None
                self.local_playback.connected = False
                self.local_playback.state = {}
                self.publish()
            await asyncio.sleep(2)


async def main():
    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    player = Player()
    bus.export('/org/mpris/MediaPlayer2', Root())
    bus.export('/org/mpris/MediaPlayer2', player)
    await bus.request_name('org.mpris.MediaPlayer2.spotify_soloist')
    await asyncio.gather(player.watch(), player.watch_account())


def cli():
    asyncio.run(main())


if __name__ == '__main__':
    cli()
