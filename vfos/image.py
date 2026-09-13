"""ISO assembly from a complete, verified VFOS live tree."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .common import Error, atomic_json, digest
from .packages import Database
from .release import require_qualified


def image(root: Path, media: Path, output: Path, cpu: str):
    manifest = json.loads((media / "manifest.json").read_text())
    require_qualified(manifest, cpu)
    if manifest.get("cpu") != cpu:
        raise Error("image CPU profile mismatch")
    state = Database(root).query()
    if state["cpu"] != cpu or state["rebuild"]:
        raise Error("live root profile mismatch or pending ABI rebuilds")
    if Database(root).verify(strict=True):
        raise Error("live root differs from its package manifests")
    if any(p.get("development_only", True) for p in state["packages"].values()):
        raise Error("live root contains host-built development packages")
    for path in ("usr/lib/grub/i386-pc", "usr/lib/grub/i386-efi", "usr/lib/grub/x86_64-efi",
                 "usr/bin/vfos", "boot/vmlinuz-live", "boot/initramfs-live.img"):
        if not (root / path).exists():
            raise Error(f"missing image input: {path}")
    for package in manifest["packages"].values():
        filename = package["file"]
        if Path(filename).name != filename or digest(media / "packages" / filename) != package["sha256"]:
            raise Error("offline media package checksum mismatch")
    # No installed-system unlock keys may ever enter an unencrypted live image.
    for directory in (root, media):
        if any(p.name == "root.key" or p.suffix == ".key" for p in directory.rglob("*")):
            raise Error("private key found in live image input")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise Error(f"output already exists: {output}")
    for tool in ("mksquashfs", "bwrap"):
        if not shutil.which(tool):
            raise Error(f"missing ISO assembly tool: {tool}")
    with tempfile.TemporaryDirectory(prefix="vfos-iso-") as td:
        tree = Path(td) / "iso"
        (tree / "boot/grub").mkdir(parents=True)
        (tree / "LiveOS").mkdir()
        shutil.copytree(media, tree / "vfos")
        subprocess.run(["mksquashfs", str(root), str(tree / "LiveOS/squashfs.img"), "-noappend", "-comp", "xz", "-all-root", "-mkfs-time", "0"], check=True)
        for name in ("vmlinuz-live", "initramfs-live.img"):
            shutil.copyfile(root / "boot" / name, tree / "boot" / name)
        (tree / "boot/grub/grub.cfg").write_text("set timeout=3\nmenuentry 'VFOS live installer' {\n linux /boot/vmlinuz-live root=live:CDLABEL=VFOS rd.live.image ro\n initrd /boot/initramfs-live.img\n}\n")
        # Run the VFOS GRUB tool with all three targets in its compiled-in
        # /usr/lib/grub. Passing -d selects *one* target and loses mixed firmware.
        subprocess.run(["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", str(root.resolve()), "/",
                        "--bind", td, "/work", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                        "--clearenv", "--setenv", "PATH", "/usr/bin:/usr/sbin:/bin:/sbin",
                        "grub-mkrescue", "-o", "/work/output.iso", "/work/iso", "--", "-volid", "VFOS"], check=True)
        shutil.copyfile(Path(td) / "output.iso", output)
    atomic_json(output.with_suffix(".manifest.json"), manifest)
    output.with_suffix(output.suffix + ".sha256").write_text(digest(output) + "  " + output.name + "\n")
