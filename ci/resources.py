#!/usr/bin/env python3
"""Record runner capacity; no x86-64-v3 package may execute on a lesser CPU."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--cpu', choices=['x86-64-v1','x86-64-v3'], required=True)
a = p.parse_args()
info = Path('/proc/cpuinfo').read_text()
flags = set(next(line.split(':',1)[1] for line in info.splitlines() if line.startswith('flags')).split())
# Linux calls SSE3 pni and CMPXCHG16B cx16; OSXSAVE is exposed through usable AVX.
v3 = {'cx16','lahf_lm','popcnt','pni','ssse3','sse4_1','sse4_2','avx','avx2','bmi1','bmi2','f16c','fma','movbe','xsave'}
if not ({'abm','lzcnt'} & flags):
    v3.add('abm')
missing = sorted(v3 - flags) if a.cpu == 'x86-64-v3' else []
report = {'cpu':a.cpu,'logical_cpus':os.cpu_count(),'memory':Path('/proc/meminfo').read_text(),
          'disk_free_bytes':shutil.disk_usage('.').free,'missing_cpu_flags':missing,
          'uname':list(os.uname()),'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0]}
print(json.dumps(report, indent=2))
if missing:
    raise SystemExit('runner cannot execute the v3 build/test profile')
if report['disk_free_bytes'] < 2 * 1024**3:
    raise SystemExit('less than 2 GiB free disk space')
