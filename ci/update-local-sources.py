#!/usr/bin/env python3
"""Refresh the explicit input inventory shipped by the local vfos-tools recipe."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
recipe = root / 'recipes/vfos-tools/recipe.sh'
lines = recipe.read_text().splitlines()
meta = json.loads(lines[1][8:])
files = []
for directory in ('vfos','profiles','recipes','config','sessions','bin'):
    files.extend(p for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
meta['local_files'] = {p.relative_to(root).as_posix():'files/'+p.relative_to(root).as_posix() for p in sorted(files)}
lines[1] = '# vfos: ' + json.dumps(meta, sort_keys=True)
recipe.write_text('\n'.join(lines)+'\n')
