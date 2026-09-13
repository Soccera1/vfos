from pathlib import Path
import tempfile
import unittest
from vfos.common import Error, resolve_target


class TargetPaths(unittest.TestCase):
    def test_absolute_links_resolve_inside_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'usr/bin').mkdir(parents=True)
            (root/'usr/bin/python3.14').write_text('target interpreter')
            (root/'usr/bin/python3').symlink_to('/usr/bin/python3.14')
            self.assertEqual(root/'usr/bin/python3.14', resolve_target(root, 'usr/bin/python3'))

    def test_escaping_links_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'escape').symlink_to('../outside')
            with self.assertRaises(Error):
                resolve_target(root, 'escape')

    def test_link_loops_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'a').symlink_to('b')
            (root/'b').symlink_to('a')
            with self.assertRaises(Error):
                resolve_target(root, 'a')
