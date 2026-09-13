#!/usr/bin/env python3
"""Build the pinned development package and write a transferable artifact index."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vfos.build import Builder
from vfos.common import CPUS, atomic_json, digest
from vfos.packages import Package
from vfos.recipes import Repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu', required=True, choices=CPUS)
    parser.add_argument('--output', type=Path, default=Path('out'))
    parser.add_argument('--cache', type=Path, default=Path('cache'))
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    repo = Repository(Path('recipes'))
    builder = Builder(repo, args.cpu, args.cache, args.output / 'packages', host_tools=True, offline=args.offline)
    archive = builder.build(['hello'])['hello']
    checksum = digest(archive)
    with Package(archive, checksum) as package:
        manifest = {
            'format': 1,
            'cpu': args.cpu,
            'name': 'hello',
            'archive': archive.relative_to(args.output.resolve()).as_posix(),
            'sha256': checksum,
            'build_id': package.meta['build_id'],
            'development_only': True,
            'sources': repo.get('hello').meta['sources'],
        }
    atomic_json(args.output / 'smoke.json', manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
