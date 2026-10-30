import tempfile
import unittest
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

from scripts.freeze import freeze


class FreezeTest(unittest.TestCase):
    def test_direct_dependencies_and_failure_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'requirements.txt'
            path.write_text('# Direct\nMarkdown==1.0  # renderer\nruff==1.0\n')
            versions = {'Markdown': '2.0', 'ruff': '3.0', 'new-package': '4.0'}
            with patch('scripts.freeze.version', side_effect=lambda name: versions[name]):
                freeze(path, ['new-package', 'RUFF'])
            expected = '# Direct\nMarkdown==2.0  # renderer\nruff==3.0\nnew-package==4.0\n'
            self.assertEqual(path.read_text(), expected)
            with patch('scripts.freeze.version', side_effect=PackageNotFoundError):
                with self.assertRaisesRegex(ValueError, 'package not installed'):
                    freeze(path)
            self.assertEqual(path.read_text(), expected)
            path.write_text('-r other.txt\n')
            with self.assertRaisesRegex(ValueError, 'unsupported requirement'):
                freeze(path)
            self.assertEqual(path.read_text(), '-r other.txt\n')
