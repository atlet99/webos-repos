import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build


class SignatureTest(unittest.TestCase):
    def test_signed_unsigned_and_tampered_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'packages').mkdir()
            output = root / 'site'
            (output / 'packages').mkdir(parents=True)
            ipk = root / 'packages' / 'app.ipk'
            ipk.write_bytes(b'package contents')
            cert = Path(str(ipk) + '.cert.pem')
            sig = Path(str(ipk) + '.sig')
            private = root / 'private.pem'
            pins = {}
            with patch.object(build, 'ROOT', root), patch.dict('os.environ', {'CI': ''}):
                self.assertIsNone(build.verify_signature(ipk, 'org.example.app', output, pins))
                subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                                '-subj', '/CN=Test', '-keyout', str(private), '-out', str(cert)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                public = subprocess.check_output(['openssl', 'x509', '-in', str(cert), '-pubkey', '-noout'])
                subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(private), '-out', str(sig), str(ipk)], check=True)
                with patch.dict('os.environ', {'CI': 'true'}):
                    with self.assertRaisesRegex(ValueError, 'unregistered signing key'):
                        build.verify_signature(ipk, 'org.example.app', output, pins)
                result = build.verify_signature(ipk, 'org.example.app', output, pins)
                self.assertEqual(result['algorithm'], 'rsa-pkcs1v15-sha256')
                self.assertTrue(result['signatureUrl'].endswith('/packages/app.ipk.sig'))
                self.assertEqual((output / 'packages' / sig.name).read_bytes(), sig.read_bytes())
                self.assertEqual((output / 'keys' / 'org.example.app.pem').read_bytes(), public)
                self.assertEqual(pins['org.example.app'], result['publicKeySha256'])
                subprocess.run(['openssl', 'req', '-x509', '-new', '-key', str(private), '-days', '1',
                                '-subj', '/CN=Renewed', '-out', str(cert)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.assertEqual(build.verify_signature(ipk, 'org.example.app', output, pins)['publicKeySha256'],
                                 result['publicKeySha256'])
                other = root / 'other.pem'
                cert_original = cert.read_bytes()
                subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                                '-subj', '/CN=Other', '-keyout', str(other), '-out', str(cert)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                with self.assertRaisesRegex(ValueError, 'does not match trusted key'):
                    build.verify_signature(ipk, 'org.example.app', output, pins)
                cert.write_bytes(cert_original)
                ipk.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'invalid.*signature'):
                    build.verify_signature(ipk, 'org.example.app', output, pins)
                sig.unlink()
                with self.assertRaisesRegex(ValueError, 'requires'):
                    build.verify_signature(ipk, 'org.example.app', output, pins)
                pins.clear()
                with self.assertRaisesRegex(ValueError, 'requires'):
                    build.verify_signature(ipk, 'org.example.app', output, pins)
