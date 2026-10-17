"""Setup reads only owned private files and imports the validated bytes."""

import importlib.util
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('setup', Path(__file__).parents[1]/'scripts/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupInputTests(unittest.TestCase):
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
