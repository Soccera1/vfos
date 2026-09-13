import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vfos.common import Error
from vfos.kernel import update

UUID = '12345678-1234-1234-1234-123456789abc'


class Kernel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for p in ('boot/grub','usr/lib/modules/6.12-vfos','etc'):
            (self.root/p).mkdir(parents=True,exist_ok=True)
        (self.root/'boot/vmlinuz-6.12-vfos').write_text('kernel')
        (self.root/'boot/grub/grub.cfg').write_text('old menu')

    def runner(self, argv, capture=False, **kwargs):
        if argv[0] == 'findmnt':
            return json.dumps({'filesystems':[{'fstype':'xfs','uuid':UUID,'source':'/dev/sda3'}]})
        if argv[0] == 'lsblk':
            return 'part'
        if 'dracut' in argv:
            (self.root / argv[-1].lstrip('/')).write_bytes(b'initramfs')

    def test_update_switches_menu_after_success(self):
        with patch('os.geteuid',return_value=0):
            update('6.12-vfos',self.root,self.runner)
        self.assertIn('vmlinuz-6.12-vfos',(self.root/'boot/grub/grub.cfg').read_text())
        self.assertEqual(0o600,(self.root/'boot/initramfs-6.12-vfos.img').stat().st_mode & 0o777)

    def test_failed_dracut_preserves_existing_boot(self):
        destination = self.root/'boot/initramfs-6.12-vfos.img'
        destination.write_bytes(b'previous')
        def fail(argv, **kwargs):
            if 'dracut' in argv:
                raise Error('injected dracut failure')
            return self.runner(argv, **kwargs)
        with patch('os.geteuid',return_value=0), self.assertRaises(Error):
            update('6.12-vfos',self.root,fail)
        self.assertEqual(b'previous',destination.read_bytes())
        self.assertEqual('old menu',(self.root/'boot/grub/grub.cfg').read_text())
        self.assertFalse(list((self.root/'boot').glob('.vfos-initramfs-*')))
