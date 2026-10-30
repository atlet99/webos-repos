import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build


class CleanupTest(unittest.TestCase):
    def test_old_versions_removed_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packages = root / 'packages'
            packages.mkdir()
            (root / 'packages.json').write_text('{}')
            (root / 'repositories.json').write_text('[]')
            old = packages / 'app_1.9_all.ipk'
            new = packages / 'app_1.10_all.ipk'
            old.write_bytes(b'old')
            new.write_bytes(b'new')
            old_sig = Path(str(old) + '.sig')
            old_cert = Path(str(old) + '.cert.pem')
            old_sig.write_bytes(b'signature')
            old_cert.write_bytes(b'certificate')
            description = packages / 'app.md'
            description.write_text('Description')

            def read_package(path):
                version = '1.9' if path == old else '1.10'
                return {'id': 'org.example.app', 'version': version, 'title': 'Example'}, None

            with patch.object(build, 'ROOT', root), patch.object(build, 'read_package', side_effect=read_package), \
                 patch.object(build, 'repository_url', return_value='https://github.com/example/repo'):
                with patch.object(build, 'add_description', side_effect=ValueError('invalid description')):
                    with self.assertRaisesRegex(ValueError, 'invalid description'):
                        build.main()
                self.assertTrue(old.exists())
                self.assertTrue(old_sig.exists())
                build.main()
                self.assertFalse(old.exists())
                self.assertFalse(old_sig.exists())
                self.assertFalse(old_cert.exists())
                self.assertTrue(new.exists())
                self.assertTrue(description.exists())
                catalog = json.loads((root / '_site' / 'apps.json').read_text())
                self.assertEqual(catalog['packages'][0]['manifest']['version'], '1.10')
