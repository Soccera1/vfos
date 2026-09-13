"""Boot configuration shared by installation and kernel updates."""
from __future__ import annotations

from pathlib import Path
import re

from .common import Error

TARGETS = {"bios": "i386-pc", "efi32": "i386-efi", "efi64": "x86_64-efi"}
FALLBACKS = {"i386-efi": "BOOTIA32.EFI", "x86_64-efi": "BOOTX64.EFI"}
BASE_MODULES = "part_gpt normal configfile search search_fs_uuid xfs linux gzio test echo reboot halt".split()
CRYPT_MODULES = "cryptodisk luks2 pbkdf2 argon2 gcry_rijndael gcry_sha256 gcry_sha512".split()
# Conservative feature contract; must be tested with the pinned GRUB/xfsprogs pair.
XFS_OPTIONS = ["-m", "crc=1,bigtime=0,reflink=0,inobtcount=0,rmapbt=0,metadir=0", "-i", "sparse=0,nrext64=0,exchange=0", "-n", "ftype=1,parent=0"]


def uuid(value):
    if not re.fullmatch(r"[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}", value):
        raise Error("invalid filesystem/LUKS UUID")
    return value.lower()


def kernel_version(value):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._+-]*", value):
        raise Error("invalid kernel version")
    return value


def early_config(root_uuid, luks_uuid=None):
    lines = []
    if luks_uuid:
        # Retry is explicit; no automatic key or fallback password on unencrypted media.
        lines += ["while ! cryptomount -u " + uuid(luks_uuid).replace("-", "") + "; do",
                  "  echo 'Unlock failed. Please try again.'", "done"]
    lines += [f"search --no-floppy --fs-uuid --set=root {uuid(root_uuid)}", "set prefix=($root)/boot/grub", "configfile $prefix/grub.cfg"]
    return "\n".join(lines) + "\n"


def grub_config(root_uuid, version, luks_uuid=None):
    version = kernel_version(version)
    params = f"root=UUID={uuid(root_uuid)} ro rootfstype=xfs"
    if luks_uuid:
        params += f" rd.luks.uuid=luks-{uuid(luks_uuid)}"
    return ("set default=0\nset timeout=3\nmenuentry 'VFOS GNU/Linux' {\n"
            f"  linux /boot/vmlinuz-{version} {params}\n"
            f"  initrd /boot/initramfs-{version}.img\n}}\n")


def dracut_config(encrypted):
    result = 'hostonly="no"\nadd_dracutmodules+=" rootfs-block kernel-modules "\nfilesystems+=" xfs "\n'
    if encrypted:
        result += ('add_dracutmodules+=" crypt dm "\n'
                   'install_items+=" /etc/crypttab /etc/cryptsetup-keys.d/root.key "\n')
    return result


def check_core_size(path: Path, partition_bytes=1024 * 1024):
    # grub-bios-setup needs its sector list and redundancy in addition to core.img.
    if path.stat().st_size > partition_bytes - 64 * 1024:
        raise Error("BIOS core image exceeds the 1 MiB embedding budget; refuse installation")


def install_boot(run, root, disk, root_uuid, version, luks_uuid=None, firmware=None):
    """root is mounted; execute tools *inside* it, preserving /boot encryption."""
    modules = BASE_MODULES + (CRYPT_MODULES if luks_uuid else [])
    grub = root / "boot/grub"
    grub.mkdir(parents=True, exist_ok=True)
    (grub / "early.cfg").write_text(early_config(root_uuid, luks_uuid))
    (grub / "grub.cfg").write_text(grub_config(root_uuid, version, luks_uuid))
    (root / "etc/dracut.conf.d").mkdir(parents=True, exist_ok=True)
    (root / "etc/dracut.conf.d/10-vfos.conf").write_text(dracut_config(bool(luks_uuid)))
    run(["chroot", str(root), "dracut", "--force", "--kver", kernel_version(version), f"/boot/initramfs-{version}.img"])
    (root / f"boot/initramfs-{version}.img").chmod(0o600)
    for target in TARGETS.values():
        # Copy the complete target module tree to encrypted /boot for subsequent use.
        run(["chroot", str(root), "cp", "-a", f"/usr/lib/grub/{target}", "/boot/grub/"])
        out = f"/boot/grub/{target}/core.img" if target == "i386-pc" else "/efi/EFI/BOOT/" + FALLBACKS[target]
        (root / out.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
        run(["chroot", str(root), "grub-mkimage", "-O", target, "-p", "/boot/grub", "-c", "/boot/grub/early.cfg", "-o", out, *modules])
        if target == "i386-pc":
            check_core_size(root / out.lstrip("/"))
            run(["chroot", str(root), "grub-bios-setup", "-d", "/boot/grub/i386-pc", disk])
    if firmware in ("efi32", "efi64"):
        # NVRAM failure is reported by the caller; removable fallback paths already exist.
        run(["chroot", str(root), "efibootmgr", "--create", "--disk", disk, "--part", "2", "--label", "VFOS",
             "--loader", "\\EFI\\BOOT\\" + FALLBACKS[TARGETS[firmware]]])
