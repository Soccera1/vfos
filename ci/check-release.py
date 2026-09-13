#!/usr/bin/env python3
"""Report development readiness; enforce it only when explicitly requested."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vfos.common import atomic_json
from vfos.recipes import Repository
from vfos.release import readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-ready', action='store_true')
    args = parser.parse_args()
    report = readiness(Repository(Path('recipes')), Path('profiles'))
    atomic_json(Path('out/readiness.json'), report)
    lines = ['## VFOS development readiness', '',
             '**Installable release: ' + ('ready' if report['ready'] else 'not ready') + '**', '',
             f"Available recipes: {len(report['available_recipes'])}", '',
             f"Missing recipes: {len(report['missing_recipes'])}", '',
             '### Missing recipe closure', '', ', '.join(report['missing_recipes']) or 'None', '',
             '### Release blockers', '']
    lines += ['- ' + blocker for blocker in report['release'].get('blockers', [])]
    summary = '\n'.join(lines) + '\n'
    Path('out/readiness.md').write_text(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write(summary)
    print(summary)
    return 1 if args.require_ready and not report['ready'] else 0


if __name__ == '__main__':
    sys.exit(main())
