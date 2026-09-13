#!/usr/bin/env python3
"""Verify a downloaded build artifact, then install/run/remove it privately."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vfos.common import CPUS, Error, atomic_json, identity, relative_path
from vfos.packages import Database, Package


def verify(manifest_path, cpu):
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('format') != 1 or manifest.get('cpu') != cpu or manifest.get('name') != 'hello' or manifest.get('development_only') is not True:
        raise Error('unexpected development artifact manifest')
    relative = relative_path(manifest['archive'])
    base = manifest_path.parent.resolve()
    archive = (base / relative).resolve()
    if base not in archive.parents:
        raise Error('artifact path escapes download directory')
    with Package(archive, manifest['sha256']) as package:
        meta = package.meta
        if meta['name'] != 'hello' or meta['cpu'] != cpu or meta.get('development_only') is not True:
            raise Error('downloaded package does not match expected name/profile/provenance')
        if meta.get('build_id') != manifest['build_id'] or identity(meta.get('inputs', {})) != manifest['build_id']:
            raise Error('downloaded package build inputs do not match its build identity')
        if meta['inputs'].get('recipe_metadata', {}).get('sources') != manifest['sources']:
            raise Error('downloaded package source manifest mismatch')
        with tempfile.TemporaryDirectory(prefix='vfos-smoke-') as directory:
            root = Path(directory)
            db = Database(root)
            db.install(package)
            if db.verify(strict=True):
                raise Error('installed package failed verification')
            executable = root / 'usr/bin/hello'
            output = subprocess.check_output([str(executable)], text=True, timeout=30, env={'LC_ALL':'C'}).strip()
            if output != 'Hello, world!':
                raise Error('installed GNU hello produced unexpected output')
            db.remove('hello')
            if executable.exists() or db.query()['packages']:
                raise Error('package removal was incomplete')
    return {'cpu':cpu, 'sha256':manifest['sha256'], 'build_id':manifest['build_id'],
            'checks':{'download_integrity':True, 'provenance':True, 'install':True,
                      'execute':True, 'verify':True, 'remove':True}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--cpu', choices=CPUS, required=True)
    p.add_argument('--report', type=Path, default=Path('out/package-verification.json'))
    args = p.parse_args()
    try:
        report = verify(args.manifest, args.cpu)
    except (Error, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        atomic_json(args.report, {'cpu':args.cpu, 'passed':False, 'error':str(error)})
        raise SystemExit(str(error))
    atomic_json(args.report, {'passed':True, **report})
    print(json.dumps(report, indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write(f"## Verified {args.cpu} development package\n\n")
            summary.write("Download integrity, provenance, install, execution, file verification and removal passed.\n\n")
            summary.write(f"Archive SHA256: `{report['sha256']}`\n\n")
            summary.write("This is a GNU hello development artifact, not a bootable VFOS release.\n")


if __name__ == '__main__':
    main()
