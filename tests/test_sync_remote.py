import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import sync_remote
from tests.test_ipk_archive import member


def ipk_bytes(app_id, version, extra=b''):
    info = json.dumps({'id': app_id, 'version': version, 'title': 'Example'}).encode()
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        item = tarfile.TarInfo('usr/palm/applications/' + app_id + '/appinfo.json')
        item.size = len(info)
        archive.addfile(item, io.BytesIO(info))
        if extra:
            marker = tarfile.TarInfo('usr/palm/applications/' + app_id + '/marker')
            marker.size = len(extra)
            archive.addfile(marker, io.BytesIO(extra))
    return b'!<arch>\n' + member('debian-binary/', b'2.0\n') + member('data.tar.gz/', data.getvalue())


class SyncRemoteTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)
        self.packages = self.directory / 'packages'
        self.packages.mkdir()
        self.manifest = self.directory / 'remote-packages.json'

    def _cleanup(self):
        for path in sorted(self.directory.rglob('*'), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.directory.rmdir()

    def source(self, name, payload):
        path = self.directory / name
        path.write_bytes(payload)
        return 'file://' + str(path)

    def run_sync(self, configs):
        self.manifest.write_text(json.dumps(configs), encoding='utf-8')
        with patch.object(sync_remote, 'MANIFEST', self.manifest), patch.object(sync_remote, 'PACKAGES', self.packages):
            sync_remote.main(self.packages)

    def test_downloads_package(self):
        self.run_sync({'org.example.app': {'url': self.source('new.ipk', ipk_bytes('org.example.app', '1.0')), 'filename': 'Example.ipk'}})
        target = self.packages / 'Example.ipk'
        self.assertEqual(sync_remote.read_package(target)[0]['version'], '1.0')
        self.assertEqual(list(self.packages.glob('.*.download')), [])

    def test_same_content_is_kept(self):
        url = self.source('new.ipk', ipk_bytes('org.example.app', '1.0'))
        self.run_sync({'org.example.app': {'url': url, 'filename': 'Example.ipk'}})
        before = (self.packages / 'Example.ipk').read_bytes()
        self.run_sync({'org.example.app': {'url': url, 'filename': 'Example.ipk'}})
        self.assertEqual((self.packages / 'Example.ipk').read_bytes(), before)

    def test_older_version_is_skipped(self):
        self.run_sync({'org.example.app': {'url': self.source('new.ipk', ipk_bytes('org.example.app', '2.0')), 'filename': 'Example.ipk'}})
        before = (self.packages / 'Example.ipk').read_bytes()
        self.run_sync({'org.example.app': {'url': self.source('old.ipk', ipk_bytes('org.example.app', '1.0')), 'filename': 'Example.ipk'}})
        self.assertEqual((self.packages / 'Example.ipk').read_bytes(), before)

    def test_rebuilt_same_version_is_accepted(self):
        self.run_sync({'org.example.app': {'url': self.source('new.ipk', ipk_bytes('org.example.app', '1.0')), 'filename': 'Example.ipk'}})
        rebuilt = ipk_bytes('org.example.app', '1.0', b'repackaged')
        self.run_sync({'org.example.app': {'url': self.source('rebuilt.ipk', rebuilt), 'filename': 'Example.ipk'}})
        self.assertEqual((self.packages / 'Example.ipk').read_bytes(), rebuilt)

    def test_foreign_application_id_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, 'org.example.app'):
            self.run_sync({'org.example.app': {'url': self.source('new.ipk', ipk_bytes('org.other.app', '1.0')), 'filename': 'Example.ipk'}})

    def test_one_broken_source_does_not_stop_the_others(self):
        configs = {
            'org.example.app': {'url': self.source('new.ipk', ipk_bytes('org.example.app', '1.0')), 'filename': 'Example.ipk'},
            'org.broken.app': {'url': 'file://' + str(self.directory / 'missing.ipk'), 'filename': 'Broken.ipk'},
        }
        with self.assertRaisesRegex(SystemExit, 'org.broken.app'):
            self.run_sync(configs)
        self.assertTrue((self.packages / 'Example.ipk').is_file())


if __name__ == '__main__':
    unittest.main()