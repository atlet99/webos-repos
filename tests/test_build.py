import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import build


class BuildTest(unittest.TestCase):
    def test_repository_remote_formats(self):
        for remote in ('git@github.com:owner/repo.git', 'https://github.com/owner/repo.git',
                       'ssh://git@github.com/owner/repo.git'):
            with self.subTest(remote=remote), patch.object(build.subprocess, 'run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = remote
                self.assertEqual(build.repository_url(), 'https://github.com/owner/repo')

    def test_catalog_and_duplicate_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'packages').mkdir()
            (root / 'descriptions').mkdir()
            (root / 'packages.json').write_text('{}')
            (root / 'repositories.json').write_text('[]')
            data = root / 'data.tar.gz'
            info = json.dumps({'id': 'org.example.app', 'version': '1.0', 'title': '<App>', 'icon': 'icon.png'}).encode()
            with tarfile.open(data, 'w:gz') as tar:
                for name, content in [('appinfo.json', info), ('icon.png', b'icon')]:
                    member = tarfile.TarInfo('usr/palm/applications/org.example.app/' + name)
                    member.size = len(content)
                    tar.addfile(member, io.BytesIO(content))
            ipk = root / 'packages' / 'app.ipk'
            subprocess.run(['ar', '-rc', str(ipk), str(data)], check=True)
            original = build.ROOT
            build.ROOT = root
            repo_patch = patch.object(build, 'repository_url', return_value='https://github.com/example/repository')
            repo_patch.start()
            try:
                output = root / 'output'
                output.mkdir()
                with self.assertRaisesRegex(ValueError, r'create .*packages/app\.md'):
                    build.build(output)
                (root / 'packages' / 'app.md').write_text('# Тест\n\n[Сайт](https://example.org) и **описание**\n\nhttps://example.com/path.', encoding='utf-8')
                (root / 'packages' / 'app.json').write_text('{"rootRequired": true}')
                output = root / 'successful'
                output.mkdir()
                build.build(output)
                entry = json.loads((output / 'apps.json').read_text())['packages'][0]
                manifest = entry['manifest']
                self.assertEqual(manifest['ipkHash']['sha256'], hashlib.sha256(ipk.read_bytes()).hexdigest())
                self.assertTrue(manifest['rootRequired'])
                self.assertEqual((output / 'icons' / 'org.example.app.png').read_bytes(), b'icon')
                self.assertIn('&lt;App&gt;', (output / 'index.html').read_text())
                self.assertEqual(entry['shortDescription'], 'Тест Сайт и описание https://example.com/path .')
                self.assertTrue(entry['fullDescriptionUrl'].endswith('/descriptions/org.example.app.html'))
                rendered = (output / 'descriptions' / 'org.example.app.html').read_text()
                self.assertIn('<a href="https://example.org">Сайт</a>', rendered)
                self.assertIn('<strong>описание</strong>', rendered)
                self.assertIn('<a href="https://example.com/path">https://example.com/path</a>.', rendered)
                self.assertIn('<a href="https://github.com/example/repository">Репозиторий приложений</a>', rendered)
                self.assertEqual(manifest['sourceUrl'], 'https://github.com/example/repository')
                versioned = root / 'packages' / 'app_1.0_all.ipk'
                ipk.rename(versioned)
                versioned_output = root / 'versioned'
                versioned_output.mkdir()
                build.build(versioned_output)
                versioned_entry = json.loads((versioned_output / 'apps.json').read_text())['packages'][0]
                self.assertTrue(versioned_entry['manifest']['ipkUrl'].endswith('/app_1.0_all.ipk'))
                self.assertTrue(versioned_entry['manifest']['rootRequired'])
                self.assertIn('<strong>описание</strong>', (versioned_output / 'descriptions' / 'org.example.app.html').read_text())
                (root / 'packages' / 'app_1.0_all.md').write_text('Версионное описание')
                specific_output = root / 'specific'
                specific_output.mkdir()
                build.build(specific_output)
                self.assertIn('Версионное описание', (specific_output / 'descriptions' / 'org.example.app.html').read_text())
                (root / 'packages' / 'second.ipk').write_bytes(versioned.read_bytes())
                other = root / 'other'
                other.mkdir()
                with self.assertRaisesRegex(ValueError, 'multiple IPKs'):
                    build.build(other)
            finally:
                repo_patch.stop()
                build.ROOT = original

    def test_external_pages_relative_urls_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'packages').mkdir()
            (root / 'packages.json').write_text('{}')
            (root / 'repositories.json').write_text('["https://example.org/catalog/apps.json"]')
            pages = {
                'https://example.org/catalog/apps.json': {
                    'packages': [{'id': 'org.example.app', 'title': 'Example',
                                  'manifestUrl': '../manifests/app.json', 'iconUri': 'icon.png',
                                  'fullDescriptionUrl': 'details.html'}],
                    'paging': {'nextUrl': 'page2.json'}},
                'https://example.org/manifests/app.json': {
                    'id': 'org.example.app', 'version': '2.0', 'ipkUrl': '../app.ipk',
                    'ipkHash': {'sha256': 'a' * 64}},
                'https://example.org/catalog/page2.json': {'packages': []},
            }
            original = build.ROOT
            build.ROOT = root
            try:
                with patch.object(build, 'fetch_json', side_effect=lambda url: pages[url]):
                    output = root / 'output'
                    output.mkdir()
                    build.build(output)
                    entry = json.loads((output / 'apps.json').read_text())['packages'][0]
                    self.assertEqual(entry['manifest']['ipkUrl'], 'https://example.org/app.ipk')
                    self.assertEqual(entry['iconUri'], 'https://example.org/catalog/icon.png')
                    self.assertEqual(entry['fullDescriptionUrl'], 'https://example.org/catalog/details.html')
                    self.assertEqual(entry['manifest']['version'], '2.0')
                    self.assertEqual(entry['fullDescriptionUrl'], 'https://example.org/catalog/details.html')
                    del pages['https://example.org/catalog/apps.json']['packages'][0]['fullDescriptionUrl']
                    missing = root / 'missing'
                    missing.mkdir()
                    with self.assertRaisesRegex(ValueError, 'create descriptions/org.example.app.html'):
                        build.build(missing)
                    (root / 'descriptions').mkdir()
                    (root / 'descriptions' / 'org.example.app.html').write_text('<p>External description</p>')
                    supplied = root / 'supplied'
                    supplied.mkdir()
                    build.build(supplied)
                    entry = json.loads((supplied / 'apps.json').read_text())['packages'][0]
                    self.assertTrue(entry['fullDescriptionUrl'].endswith('/descriptions/org.example.app.html'))
                    self.assertEqual(entry['shortDescription'], 'External description')
                    pages['https://example.org/catalog/page2.json']['packages'] = pages['https://example.org/catalog/apps.json']['packages']
                    other = root / 'other'
                    other.mkdir()
                    with self.assertRaisesRegex(ValueError, 'duplicate package ID'):
                        build.build(other)
            finally:
                build.ROOT = original


if __name__ == '__main__':
    unittest.main()
