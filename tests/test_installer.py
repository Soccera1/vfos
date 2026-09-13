import dataclasses
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from vfos.boot import check_core_size, dracut_config, early_config, grub_config
from vfos.common import Error
from vfos.installer import Answers, Cancelled, Dialog, Disk, KDFS, execute, inventory, layout, partition_path, partition_script, plan
from vfos.release import matrix, require_qualified

UUID = '12345678-1234-1234-1234-123456789abc'


class Installer(unittest.TestCase):
    def disk(self, sector=512):
        return Disk('/dev/nvme0n1', 64 * 1024**3, sector, 'serial', '259:0', 'Test disk')

    def test_all_matrix_layouts(self):
        cases = matrix()
        self.assertEqual(18, len(cases))
        self.assertEqual(18, len({c['id'] for c in cases}))
        for case in cases:
            a = Answers(self.disk(case['logical_sector']), desktop=case['desktop'], encryption=case['encryption'], cpu=case['cpu'])
            result = plan(a)
            parts = result['partitions']
            sector = a.disk.logical_sector
            self.assertEqual(1024**2, parts[0]['size'] * sector)
            self.assertEqual((36 if sector == 512 else 260) * 1024**2, parts[1]['size'] * sector)
            for before, after in zip(parts, parts[1:]):
                self.assertEqual(before['start'] + before['size'], after['start'])
            self.assertLess((parts[-1]['start'] + parts[-1]['size']) * sector, a.disk.size)
            self.assertTrue(result['boot_on_root'])
            self.assertIsNone(result['swap'])

    def test_partition_paths(self):
        self.assertEqual('/dev/sda3', partition_path('/dev/sda', 3))
        self.assertEqual('/dev/nvme0n1p3', partition_path('/dev/nvme0n1', 3))
        self.assertEqual('/dev/mmcblk0p3', partition_path('/dev/mmcblk0', 3))

    def test_injection_and_invalid_answers(self):
        a = Answers(self.disk())
        for field, value in [('hostname','test; reboot'), ('timezone','../../etc/passwd'), ('username','root'), ('keyboard','us\nreboot'), ('locale','C'), ('encryption','luks1'), ('cpu','native')]:
            with self.subTest(field=field), self.assertRaises(Error):
                plan(dataclasses.replace(a, **{field:value}))

    def test_cancel_happens_before_media_or_subprocesses(self):
        with patch('vfos.installer.load_media') as media, patch('vfos.installer.inventory') as disks:
            with self.assertRaises(Cancelled):
                execute(Answers(self.disk()), Path('/nonexistent'), 'yes', b'password')
            media.assert_not_called()
            disks.assert_not_called()

    def test_changed_disk_identity_aborts_before_first_write(self):
        a = Answers(self.disk())
        run = Mock()
        changed = dataclasses.replace(a.disk, serial='different-disk')
        with patch('os.geteuid', return_value=0), patch('vfos.installer.load_media', return_value=({}, [])), patch('shutil.which', return_value='/usr/bin/tool'), patch('vfos.installer.inventory', return_value=[changed]):
            with self.assertRaisesRegex(Error, 'identity changed'):
                execute(a, Path('/media'), 'ERASE ' + a.disk.path, b'password', run=run, root_password=b'rootpassword')
        run.assert_not_called()

    def test_secrets_cannot_enter_plan(self):
        result = json.dumps(plan(Answers(self.disk(), encryption='argon2id')))
        self.assertNotIn('root.key', result)
        self.assertNotIn('password', result)
        self.assertNotIn('passphrase', result)

    def test_argon2_has_explicit_bounded_cost(self):
        args = KDFS['argon2id']
        self.assertEqual('65536', args[args.index('--pbkdf-memory') + 1])
        self.assertNotIn('pbkdf2', args)

    def test_inventory_excludes_mounted_mapped_readonly_disks(self):
        def disk(name, **extra):
            return {'path':'/dev/'+name, 'type':'disk', 'size':64*1024**3, 'log-sec':512, 'serial':name, 'maj:min':'8:0', 'mountpoints':[None], **extra}
        nodes = [disk('sda'), disk('sdb', children=[{'type':'part','mountpoints':['/']}]),
                 disk('sdc', children=[{'type':'part','children':[{'type':'crypt','mountpoints':[None]}]}]),
                 disk('sdd', ro=True), disk('sde', children=[{'type':'part','mountpoints':['[SWAP]']}])]
        run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps({'blockdevices':nodes})))
        self.assertEqual(['/dev/sda'], [d.path for d in inventory(run)])

    def test_dialog_cancellation(self):
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, stdout=b'')):
            with self.assertRaises(Cancelled):
                Dialog().call('--inputbox','Review','Confirm')

    def test_password_mismatch(self):
        dialog = Dialog()
        with patch.object(dialog,'call', side_effect=['a','b']):
            with self.assertRaisesRegex(Error, 'match'):
                dialog.password('Password')

    def test_one_grub_unlock_and_no_key_on_esp(self):
        early = early_config(UUID, UUID)
        self.assertEqual(1, early.count('cryptomount'))
        self.assertIn('while ! cryptomount', early)
        self.assertNotIn('root.key', early)
        cfg = grub_config(UUID, '6.12.1-vfos', UUID)
        self.assertNotIn('cryptomount', cfg)
        self.assertNotIn('/efi', dracut_config(True))
        self.assertIn('/etc/cryptsetup-keys.d/root.key', dracut_config(True))
        self.assertNotIn('root.key', dracut_config(False))

    def test_grub_injection_rejected(self):
        with self.assertRaises(Error):
            grub_config(UUID, "6.12; reboot")
        with self.assertRaises(Error):
            early_config(UUID + '\nreboot')

    def test_bios_embedding_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'core.img'
            p.write_bytes(bytes(100))
            check_core_size(p)
            with p.open('wb') as f:
                f.truncate(1024**2)
            with self.assertRaises(Error):
                check_core_size(p)

    def test_unqualified_release_never_authorizes_install(self):
        with self.assertRaisesRegex(Error, 'unqualified'):
            require_qualified({'status':'unqualified'}, 'x86-64-v1')
        with self.assertRaises(Error):
            require_qualified({'status':'qualified','development_only':False}, 'x86-64-v1')


if __name__ == '__main__':
    unittest.main()
