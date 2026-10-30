import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.build import read_package


def member(name, data):
    header = (name.ljust(16) + '0'.ljust(12) + '0'.ljust(6) + '0'.ljust(6) +
              '100644'.ljust(8) + str(len(data)).ljust(10) + '`\n').encode('ascii')
    return header + data + (b'\n' if len(data) % 2 else b'')


class IpkArchiveTest(unittest.TestCase):
    def test_gnu_ar_names_and_application_metadata(self):
        info = json.dumps({'id': 'org.example.app', 'version': '1.0', 'title': 'Example'}).encode()
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            item = tarfile.TarInfo('usr/palm/applications/org.example.app/appinfo.json')
            item.size = len(info)
            archive.addfile(item, io.BytesIO(info))
        with tempfile.TemporaryDirectory() as directory:
            ipk = Path(directory) / 'example.ipk'
            ipk.write_bytes(b'!<arch>\n' + member('debian-binary/', b'2.0\n') + member('data.tar.gz/', data.getvalue()))
            self.assertEqual(read_package(ipk)[0]['id'], 'org.example.app')
            ipk.write_bytes(b'!<arch>\n' + member('debian-binary/', b'2.0\n'))
            with self.assertRaisesRegex(ValueError, 'example.ipk.*expected one supported'):
                read_package(ipk)
