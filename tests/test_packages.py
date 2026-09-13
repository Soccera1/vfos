import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from vfos.common import Error, atomic_json, digest
from vfos.packages import Database, Package, pack


class Packages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'root'
        self.serial = 0

    def package(self, name='demo', version='1', abi='1', cpu='x86-64-v1', files=None, dependencies=None):
        self.serial += 1
        stage = self.base / f'stage-{self.serial}'
        stage.mkdir()
        for filename, content in (files or {'usr/bin/demo': 'hello', 'etc/demo.conf': 'original'}).items():
            p = stage / filename
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        archive = self.base / f'{name}-{self.serial}.pkg.tar.xz'
        pack(stage, dict(name=name, version=version, abi=abi, cpu=cpu, dependencies=dependencies or {}, development_only=True), archive)
        package = Package(archive)
        self.addCleanup(package.close)
        return package

    def test_roundtrip_verify_and_remove(self):
        pkg = self.package()
        db = Database(self.root)
        db.install(pkg)
        self.assertEqual([], db.verify())
        self.assertEqual('hello', (self.root / 'usr/bin/demo').read_text())
        db.remove('demo')
        self.assertFalse((self.root / 'usr/bin/demo').exists())
        self.assertEqual({}, db.query()['packages'])

    def test_modified_configuration_is_preserved_on_upgrade_and_remove(self):
        db = Database(self.root)
        db.install(self.package())
        config = self.root / 'etc/demo.conf'
        config.write_text('local')
        db.install(self.package(version='2', files={'usr/bin/demo':'new', 'etc/demo.conf':'new-default'}), upgrade=True)
        self.assertEqual('local', config.read_text())
        self.assertEqual('new-default', (self.root / 'etc/demo.conf.vfos-new').read_text())
        self.assertEqual([{'package':'demo', 'path':'etc/demo.conf', 'configuration':True}], db.verify())
        db.remove('demo')
        self.assertEqual('local', config.read_text())
        self.assertFalse((self.root / 'etc/demo.conf.vfos-new').exists())

    def test_unowned_and_owned_conflicts_rejected_before_writes(self):
        db = Database(self.root)
        db.install(self.package())
        with self.assertRaisesRegex(Error, 'conflict'):
            db.install(self.package('other'))
        self.assertNotIn('other', db.query()['packages'])
        p = self.root / 'usr/bin/unowned'
        p.write_text('keep')
        with self.assertRaisesRegex(Error, 'unowned'):
            db.install(self.package('other', files={'usr/bin/unowned':'overwrite'}))
        self.assertEqual('keep', p.read_text())

    def test_profile_mix_rejected(self):
        db = Database(self.root)
        db.install(self.package())
        with self.assertRaisesRegex(Error, 'CPU'):
            db.install(self.package('other', cpu='x86-64-v3'))

    def test_dependencies_and_transitive_abi_rebuild_queue(self):
        db = Database(self.root)
        with self.assertRaisesRegex(Error, 'needs'):
            db.install(self.package('client', dependencies={'demo':'1'}))
        db.install(self.package())
        db.install(self.package('client', files={'usr/bin/client':'client'}, dependencies={'demo':'1'}))
        db.install(self.package('top', files={'usr/bin/top':'top'}, dependencies={'client':'1'}))
        with self.assertRaisesRegex(Error, 'required by'):
            db.remove('demo')
        pending = db.install(self.package(abi='2'), upgrade=True)
        self.assertEqual(['client', 'top'], pending)

    def test_failed_write_rolls_back_payload_and_database(self):
        db = Database(self.root)
        db.install(self.package())
        previous = db.query()
        real_copy = db.copy
        counter = 0
        def broken_copy(src, dest):
            nonlocal counter
            if '/stage-' in str(src) or '/vfos-package-' in str(src):
                counter += 1
                if counter == 2:
                    raise OSError('injected disk failure')
            return real_copy(src, dest)
        with patch.object(db, 'copy', side_effect=broken_copy):
            with self.assertRaises(OSError):
                db.install(self.package(version='2'), upgrade=True)
        self.assertEqual(previous, db.query())
        self.assertEqual([], db.verify())
        self.assertFalse(db.journal.exists())

    def test_interrupted_transaction_recovered_on_reopen(self):
        db = Database(self.root)
        db.install(self.package())
        previous = db.query()
        db.journal.mkdir()
        db.copy(self.root / 'usr/bin/demo', db.journal / 'backup-0')
        atomic_json(db.journal / 'journal.json', {'paths':{'usr/bin/demo':'backup-0', 'usr/bin/new':None}, 'database':previous})
        (self.root / 'usr/bin/demo').write_text('partial')
        (self.root / 'usr/bin/new').write_text('partial')
        reopened = Database(self.root)
        self.assertEqual(previous, reopened.query())
        self.assertEqual('hello', (self.root / 'usr/bin/demo').read_text())
        self.assertFalse((self.root / 'usr/bin/new').exists())

    def test_symlink_ancestor_cannot_escape_root(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.root.mkdir()
        (self.root / 'usr').symlink_to(outside)
        with self.assertRaisesRegex(Error, 'symlink ancestor'):
            Database(self.root).install(self.package())
        self.assertFalse((outside / 'bin/demo').exists())

    def test_tampered_archive_rejected(self):
        p = self.package()
        with self.assertRaisesRegex(Error, 'checksum'):
            Package(p.path, '0' * 64)

    def test_archive_traversal_and_duplicate_members_rejected(self):
        package = self.package()
        for badname in ('root/../../escape', 'manifest.json'):
            path = self.base / 'bad.tar.xz'
            with tarfile.open(package.path) as source, tarfile.open(path, 'w:xz') as dest:
                for m in source.getmembers():
                    dest.addfile(m, source.extractfile(m) if m.isfile() else None)
                m = tarfile.TarInfo(badname)
                m.size = 1
                dest.addfile(m, io.BytesIO(b'x'))
            with self.assertRaises(Error):
                Package(path)
        self.assertFalse((self.base / 'escape').exists())

    def test_database_payload_forbidden(self):
        with self.assertRaisesRegex(Error, 'database'):
            self.package(files={'var/lib/vfos/state/packages.json':'{}'})

    def test_strict_builder_verification_rejects_unowned_tools(self):
        db = Database(self.root)
        db.install(self.package())
        (self.root / 'usr/bin/hidden-compiler').write_text('undeclared')
        self.assertEqual([], db.verify())
        self.assertTrue(any(r.get('unowned') for r in db.verify(strict=True)))

    def test_deterministic_archive(self):
        a = self.package()
        b = self.package()
        self.assertEqual(digest(a.path), digest(b.path))

    def test_missing_files_reported(self):
        db = Database(self.root)
        db.install(self.package())
        (self.root / 'usr/bin/demo').unlink()
        self.assertEqual('usr/bin/demo', db.verify()[0]['path'])

    def test_directory_conflict_does_not_destroy_directory(self):
        db = Database(self.root)
        (self.root / 'usr/bin/demo').mkdir(parents=True)
        with self.assertRaises(Error):
            db.install(self.package())
        self.assertTrue((self.root / 'usr/bin/demo').is_dir())


if __name__ == '__main__':
    unittest.main()
