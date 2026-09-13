"""Regenerate an installed system's initramfs without exposing its root key."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from .boot import dracut_config, grub_config, kernel_version, uuid
from .common import Error, sync_dir


def replace_text(path, text, mode=0o600):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.vfos-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        sync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def update(version, root=Path('/'), run=None):
    """The root argument permits mounted rescue targets and offline unit tests."""
    from .installer import Runner
    version = kernel_version(version)
    if os.geteuid() != 0:
        raise Error('kernel/initramfs updates require root')
    run = run or Runner()
    root = root.resolve()
    boot = root / 'boot'
    if not boot.is_dir() or boot.is_symlink() or boot.stat().st_dev != root.stat().st_dev:
        raise Error('/boot must be a directory on the root filesystem')
    if not (boot / f'vmlinuz-{version}').is_file() or not (root / f'usr/lib/modules/{version}').is_dir():
        raise Error('matching kernel and modules must be installed before regenerating initramfs')
    mounted = json.loads(run(['findmnt','--json','--target',str(root),'--output','SOURCE,FSTYPE,UUID'], capture=True))['filesystems'][0]
    if mounted['fstype'] != 'xfs':
        raise Error('VFOS kernel updates require the XFS root')
    root_uuid = uuid(mounted['uuid'])
    crypttab = root / 'etc/crypttab'
    luks_uuid = None
    root_type = run(['lsblk','--noheadings','--nodeps','--output','TYPE',mounted['source']], capture=True)
    if root_type == 'crypt':
        if crypttab.is_symlink() or not crypttab.is_file():
            raise Error('encrypted root has no safe crypttab')
        lines = [l for l in crypttab.read_text().splitlines() if l.strip() and not l.lstrip().startswith('#')]
        match = re.fullmatch(r'root UUID=([a-fA-F0-9-]+) /etc/cryptsetup-keys.d/root.key luks', '\n'.join(lines))
        if not match:
            raise Error('crypttab no longer matches the single-prompt VFOS root contract')
        luks_uuid = uuid(match[1])
        key = root / 'etc/cryptsetup-keys.d/root.key'
        if key.is_symlink() or key.parent.is_symlink() or not key.is_file() or key.stat().st_dev != root.stat().st_dev:
            raise Error('root key must remain inside encrypted root')
        if key.stat().st_uid != 0 or stat.S_IMODE(key.stat().st_mode) != 0o600 or key.stat().st_size != 64:
            raise Error('root key must be a root-owned, 0600, 64-byte file')
    elif crypttab.exists() and any(l.strip() and not l.startswith('#') for l in crypttab.read_text().splitlines()):
        raise Error('crypttab is present but the root device is not encrypted')
    conf = root / 'etc/dracut.conf.d/10-vfos.conf'
    conf.parent.mkdir(parents=True, exist_ok=True)
    replace_text(conf, dracut_config(bool(luks_uuid)))
    fd, name = tempfile.mkstemp(dir=boot, prefix='.vfos-initramfs-')
    os.close(fd)
    tmp = Path(name)
    destination = boot / f'initramfs-{version}.img'
    try:
        run(['chroot',str(root),'dracut','--force','--kver',version,'/boot/' + tmp.name])
        if tmp.stat().st_size == 0:
            raise Error('dracut produced an empty initramfs')
        tmp.chmod(0o600)
        with tmp.open('rb') as f:
            os.fsync(f.fileno())
        if destination.exists():
            if destination.is_symlink():
                raise Error('initramfs destination is a symlink')
            # Retain a rescue copy, still on encrypted /boot.
            import shutil
            shutil.copyfile(destination, destination.with_suffix('.img.previous'))
            destination.with_suffix('.img.previous').chmod(0o600)
        os.replace(tmp, destination)
        sync_dir(boot)
        # Switching the menu is last; a failed dracut never changes the boot entry.
        replace_text(boot / 'grub/grub.cfg', grub_config(root_uuid, version, luks_uuid))
    finally:
        tmp.unlink(missing_ok=True)
