import json
from pathlib import Path
import tempfile
import unittest
from vfos.common import Error, cpu_flags
from vfos.recipes import Repository
from vfos.build import fetch


class Recipes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def recipe(self, name, depends=(), tree=None):
        p = (tree or self.root) / name
        p.mkdir(parents=True)
        (p / 'recipe.sh').write_text('#!/bin/bash\n# vfos: ' + json.dumps(dict(name=name, version='1', abi='1', depends=list(depends))) + '\n' + '\n'.join(f'{s}() {{ :; }}' for s in ('prepare','build','check','stage')))

    def test_dependency_order_and_missing_recipe(self):
        self.recipe('lib')
        self.recipe('app', ['lib'])
        self.assertEqual(['lib','app'], [r.name for r in Repository(self.root).plan(['app','lib'])])
        with self.assertRaisesRegex(Error, 'missing'):
            Repository(self.root).plan(['unknown'])

    def test_cycle_has_actionable_path(self):
        self.recipe('a',['b'])
        self.recipe('b',['a'])
        with self.assertRaisesRegex(Error, 'a -> b -> a'):
            Repository(self.root).plan(['a'])

    def test_queries_do_not_execute_shell(self):
        self.recipe('a')
        sentinel = self.root / 'executed'
        with (self.root / 'a/recipe.sh').open('a') as f:
            f.write(f'\ntouch {sentinel}\n')
        Repository(self.root).plan(['a'])
        self.assertFalse(sentinel.exists())

    def test_overrides_outside_synced_tree(self):
        self.recipe('a')
        with self.assertRaisesRegex(Error, 'outside'):
            Repository(self.root, self.root)

    def test_reverse_dependency_closure(self):
        self.recipe('a')
        self.recipe('b',['a'])
        self.recipe('c',['b'])
        self.recipe('unrelated')
        self.assertEqual(['a','b','c'], [r.name for r in Repository(self.root).reverse_dependencies(['a'])])

    def test_flags_never_use_native(self):
        for cpu in ('x86-64-v1','x86-64-v3'):
            flags = cpu_flags(cpu)
            self.assertNotIn('native', flags)
            self.assertIn('-O2', flags)
            self.assertIn('-fstack-protector-strong', flags)
        self.assertIn('-march=x86-64 ', cpu_flags('x86-64-v1'))
        self.assertIn('-march=x86-64-v3 ', cpu_flags('x86-64-v3'))

    def test_offline_missing_and_corrupt_cache(self):
        source = {'filename':'source.tar.xz','sha256':'0'*64,'url':'https://example.invalid/source.tar.xz'}
        with self.assertRaisesRegex(Error, 'not cached'):
            fetch(source, self.root, offline=True)
        (self.root / ('0'*64+'-source.tar.xz')).write_text('corrupt')
        with self.assertRaisesRegex(Error, 'corrupt'):
            fetch(source, self.root, offline=True)


if __name__ == '__main__':
    unittest.main()
