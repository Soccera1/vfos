import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from vfos.common import Error, digest, identity
from vfos.packages import pack

spec = importlib.util.spec_from_file_location('package_smoke', Path(__file__).resolve().parents[1] / 'ci/package-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class CIArtifacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        stage = self.root / 'stage'
        (stage / 'usr/bin').mkdir(parents=True)
        binary = stage / 'usr/bin/hello'
        binary.write_text('#!/bin/sh\nprintf "Hello, world!\\n"\n')
        binary.chmod(0o755)
        inputs = {'recipe_metadata':{'sources':[]}}
        meta = {'name':'hello','version':'1','abi':'1','cpu':'x86-64-v1', 'development_only':True,
                'inputs':inputs,'build_id':identity(inputs),'dependencies':{}}
        self.archive = self.root / 'hello.pkg.tar.xz'
        pack(stage, meta, self.archive)
        self.index = {'format':1,'cpu':'x86-64-v1','name':'hello','development_only':True,
                      'archive':self.archive.name,'sha256':digest(self.archive),'build_id':identity(inputs),'sources':[]}
        self.manifest = self.root / 'smoke.json'
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps(self.index))

    def test_valid_transferred_artifact(self):
        report = smoke.verify(self.manifest, 'x86-64-v1')
        self.assertTrue(all(report['checks'].values()))

    def test_modified_archive_rejected_against_transfer_index(self):
        self.archive.write_bytes(self.archive.read_bytes() + b'corruption')
        with self.assertRaisesRegex(Error,'checksum mismatch'):
            smoke.verify(self.manifest, 'x86-64-v1')

    def test_wrong_cpu_rejected(self):
        with self.assertRaises(Error):
            smoke.verify(self.manifest, 'x86-64-v3')

    def test_modified_provenance_rejected(self):
        self.index['build_id'] = '0'*64
        self.save()
        with self.assertRaisesRegex(Error,'build inputs'):
            smoke.verify(self.manifest, 'x86-64-v1')

    def test_escaping_artifact_path_rejected(self):
        self.index['archive'] = '../hello.pkg.tar.xz'
        self.save()
        with self.assertRaises(Error):
            smoke.verify(self.manifest, 'x86-64-v1')
