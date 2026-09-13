#!/usr/bin/env python3
"""Validate formatter argument shapes on sparse ordinary files, never devices.

This is not evidence of GRUB or encrypted-system boot compatibility.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vfos.boot import XFS_OPTIONS

for tool in ('mkfs.xfs','mkfs.fat'):
    if not shutil.which(tool):
        raise SystemExit('missing tool: ' + tool)
with tempfile.TemporaryDirectory(prefix='vfos-fs-smoke-') as td:
    root = Path(td)
    xfs = root / 'root.xfs'
    with xfs.open('wb') as f:
        f.truncate(1024**3)
    subprocess.run(['mkfs.xfs','-N',*XFS_OPTIONS,str(xfs)],check=True)
    for sector, mib in ((512,36),(4096,260)):
        esp = root / f'esp-{sector}.fat'
        with esp.open('wb') as f:
            f.truncate(mib*1024**2)
        result = subprocess.run(['mkfs.fat','-F','32','-s','1','-S',str(sector),str(esp)],capture_output=True,text=True,check=True)
        if 'WARNING' in result.stderr.upper():
            raise SystemExit(result.stderr)
        print(f'ESP {mib} MiB, {sector}-byte sectors: formatted without warnings')
