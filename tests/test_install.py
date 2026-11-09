import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from spotify_island import cli, control
from spotify_island.common import atomic_write, config_dir, key_file, token_file


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {name: str(self.root / name) for name in (
            'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME')})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def exported_config(self):
        return subprocess.CompletedProcess([], 0, stdout='''[plugins]
enabled = ["other/plugin"]
[[plugins.source]]
name = "desktop"
kind = "path"
location = "/existing/plugins"
enabled = true
[[bar.default.capsule_group]]
id = "center"
members = ["clock", "notifications"]
''')

    def test_registration_preserves_settings_and_is_idempotent(self):
        state = Path(os.environ['XDG_STATE_HOME']) / 'noctalia/settings.toml'
        atomic_write(state, '[shell.animation]\nspeed = 2.0\n')
        with patch.object(cli, 'call', return_value=self.exported_config()):
            cli.register_plugin()
            first = tomllib.loads(state.read_text())
            cli.register_plugin()
        self.assertEqual(first, tomllib.loads(state.read_text()))
        self.assertEqual(first['shell']['animation']['speed'], 2.0)
        self.assertEqual(first['plugins']['enabled'], ['other/plugin', cli.PLUGIN_ID])
        self.assertEqual(first['plugins']['source'][0]['name'], 'desktop')
        self.assertEqual(first['bar']['default']['capsule_group'][0]['members'], ['clock', 'spotify', 'notifications'])
        self.assertTrue(list(state.parent.glob('settings.toml.backup-*')))
        plugin = Path(os.environ['XDG_DATA_HOME']) / 'spotify-island/plugins/spotify-island/plugin.toml'
        self.assertEqual(tomllib.loads(plugin.read_text())['id'], cli.PLUGIN_ID)

    def test_systemd_command_escaping(self):
        command = '/home/a user/100%/bin/spotify-island'
        cli.install_units(command)
        unit = Path(os.environ['XDG_CONFIG_HOME']) / 'systemd/user' / cli.SERVICES[0]
        self.assertIn('ExecStart="/home/a user/100%%/bin/spotify-island" run-player', unit.read_text())

    def test_reset_key_is_private_and_blank_input_preserves_old_key(self):
        atomic_write(key_file(), 'old-key\n')
        with patch('getpass.getpass', return_value='new-key'), patch.object(cli, 'call'):
            cli.setup(reset_key=True)
        self.assertEqual(key_file().read_text(), 'new-key\n')
        self.assertEqual(stat.S_IMODE(key_file().stat().st_mode), 0o600)
        with patch('getpass.getpass', return_value=''), self.assertRaises(ValueError):
            cli.setup(reset_key=True)
        self.assertEqual(key_file().read_text(), 'new-key\n')

    def test_token_requires_unambiguous_selection(self):
        cache = Path(os.environ['XDG_CACHE_HOME']) / 'spotify-player'
        atomic_write(cache / 'first_token.json', '{}')
        self.assertEqual(token_file(), cache / 'first_token.json')
        atomic_write(cache / 'second_token.json', '{}')
        with self.assertRaises(OSError):
            token_file()
        atomic_write(config_dir() / 'config.toml', 'spotify_token_file = "' + str(cache / 'second_token.json') + '"\n')
        self.assertEqual(token_file(), cache / 'second_token.json')

    def test_json_snapshot_is_exactly_one_json_document(self):
        output = io.StringIO()
        with patch('sys.argv', ['spotify-quick-control', 'snapshot', '--json']), patch.object(control, 'library_snapshot', return_value={'authorized': False, 'albums': []}), contextlib.redirect_stdout(output):
            control.cli()
        self.assertEqual(json.loads(output.getvalue()), {'ok': True, 'message': '', 'authorized': False, 'albums': []})

    def test_migration_requires_explicit_legacy_replacement(self):
        args = argparse.Namespace(no_start=False, replace_legacy=False, bar='default', group='center', no_bar=False)
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)), patch.object(cli, 'install_units') as units:
            with self.assertRaises(ValueError):
                cli.install(args)
            units.assert_not_called()


if __name__ == '__main__':
    unittest.main()
