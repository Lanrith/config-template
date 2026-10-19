"""Setup reads only owned private files and imports the validated bytes."""

import importlib.util
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('setup', Path(__file__).parents[1]/'scripts/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupInputTests(unittest.TestCase):
    def test_repository_profile_succeeds_without_environment_or_ruleset_access(self):
        def api(repository, suffix, value=None):
            self.assertEqual(repository, 'example/router')
            if suffix == '':
                return {'private': True, 'default_branch': 'main', 'permissions': {'admin': True}}
            if suffix == '/actions/secrets':
                return {'secrets': []}
            if suffix == '/actions/variables?per_page=100':
                return {'variables': []}
            self.fail('Free-compatible setup requested paid controls: '+suffix)
        with patch.object(setup, 'api', side_effect=api), patch.object(setup, 'gh') as gh, \
                patch('sys.argv', ['setup.py', 'example/router', '--signing-profile', 'repository']):
            setup.main()
        gh.assert_called_once_with('variable', 'set', 'LANRITH_SIGNING_PROFILE', '--repo',
                                   'example/router', '--body', 'repository')

    def test_a_different_selected_profile_cannot_silently_move_keys(self):
        def api(repository, suffix, value=None):
            if suffix == '':
                return {'private': True, 'default_branch': 'main', 'permissions': {'admin': True}}
            if suffix == '/actions/secrets':
                return {'secrets': []}
            return {'variables': [{'name': 'LANRITH_SIGNING_PROFILE', 'value': 'protected'}]}
        with patch.object(setup, 'api', side_effect=api), patch.object(setup, 'gh') as gh, \
                patch.object(setup, 'key_matches') as read_keys, \
                patch('sys.argv', ['setup.py', 'example/router', '--signing-profile', 'repository', '--import-keys']):
            with self.assertRaisesRegex(ValueError, 'different signing profile'):
                setup.main()
        gh.assert_not_called()
        read_keys.assert_not_called()

    def test_protected_mode_refuses_missing_capabilities_before_reading_keys(self):
        def api(repository, suffix, value=None):
            if suffix == '':
                return {'private': True, 'default_branch': 'main', 'permissions': {'admin': True}}
            raise subprocess.CalledProcessError(1, ['gh', 'api'])
        with patch.object(setup, 'api', side_effect=api), patch.object(setup, 'gh') as gh, \
                patch.object(setup, 'key_matches') as read_keys, \
                patch('sys.argv', ['setup.py', 'example/router', '--import-keys']):
            with self.assertRaises(subprocess.CalledProcessError):
                setup.main()
        gh.assert_not_called()
        read_keys.assert_not_called()

    def test_repository_profile_imports_actual_matching_keys_only_into_repository_secrets(self):
        with tempfile.TemporaryDirectory(prefix='lanrith-profile-test.', dir='/dev/shm') as temporary:
            root = Path(temporary)
            (root/'trust').mkdir()
            for name in ('boot', 'evidence'):
                subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=Lanrith Disposable Profile Test', '-keyout', str(root/(name+'.key')),
                    '-out', str(root/'trust'/(name+'.crt'))], check=True, capture_output=True)
                (root/(name+'.key')).chmod(0o600)
            def api(repository, suffix, value=None):
                if suffix == '':
                    return {'private': True, 'default_branch': 'main', 'permissions': {'admin': True}}
                if suffix == '/actions/secrets':
                    return {'secrets': []}
                return {'variables': [{'name': 'LANRITH_SIGNING_PROFILE', 'value': 'repository'}]}
            arguments = ['setup.py', 'example/router', '--signing-profile', 'repository', '--import-keys',
                         '--boot-key', str(root/'boot.key'), '--evidence-key', str(root/'evidence.key')]
            with patch.object(setup, 'ROOT', root), patch.object(setup, 'api', side_effect=api), \
                    patch.object(setup, 'gh') as gh, patch('sys.argv', arguments):
                setup.main()
            self.assertEqual(len(gh.call_args_list), 4)
            imported = {}
            for call in gh.call_args_list:
                self.assertNotIn('--env', call.args)
                self.assertEqual(call.args[:2], ('secret', 'set'))
                self.assertEqual(call.args[3:], ('--repo', 'example/router'))
                imported[call.args[2]] = call.kwargs['data']
            self.assertEqual(imported['LANRITH_BOOT_KEY'], (root/'boot.key').read_bytes())
            self.assertEqual(imported['LANRITH_EVIDENCE_KEY'], (root/'evidence.key').read_bytes())

    def test_private_material_rejects_shared_readable_linked_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'credential'
            source.write_bytes(b'synthetic protected test material')
            source.chmod(0o600)
            self.assertEqual(setup.private_material(source), source.read_bytes())
            source.chmod(0o644)
            with self.assertRaises(ValueError):
                setup.private_material(source)
            source.chmod(0o600)
            link = root/'link'
            link.symlink_to(source)
            with self.assertRaises(OSError):
                setup.private_material(link)
            hardlink = root/'shared'
            os.link(source, hardlink)
            with self.assertRaises(ValueError):
                setup.private_material(source)
            hardlink.unlink()
            source.write_bytes(b'x'*65537)
            with self.assertRaises(ValueError):
                setup.private_material(source)

    def test_real_disposable_key_must_match_the_reviewed_certificate(self):
        with tempfile.TemporaryDirectory(prefix='lanrith-setup-test.', dir='/dev/shm') as temporary:
            root = Path(temporary)
            for name in ('first', 'second'):
                subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=Lanrith Disposable Setup Test', '-keyout', str(root/(name+'.key')),
                    '-out', str(root/(name+'.crt'))], check=True, capture_output=True)
                (root/(name+'.key')).chmod(0o600)
            self.assertEqual(setup.key_matches(root/'first.key', root/'first.crt'), (root/'first.key').read_bytes())
            with self.assertRaises(ValueError):
                setup.key_matches(root/'first.key', root/'second.crt')
