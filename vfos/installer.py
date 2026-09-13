from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

from .boot import XFS_OPTIONS, install_boot, kernel_version
from .common import CPUS, Error, atomic_json, digest, identity, resolve_target
from .packages import Database, Package

MIB = 1024 * 1024
# Candidates, not hardware-qualified security recommendations. Release is gated
# on the firmware matrix in profiles/release.json.
KDFS = {"argon2id": ["--pbkdf", "argon2id", "--pbkdf-memory", "65536", "--pbkdf-parallel", "1", "--pbkdf-force-iterations", "4"],
        "pbkdf2": ["--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "600000"]}


class Cancelled(Error):
    pass


@dataclass(frozen=True)
class Disk:
    path: str
    size: int
    logical_sector: int
    serial: str
    major_minor: str
    model: str = ""

    @property
    def token(self):
        return identity(asdict(self))


@dataclass(frozen=True)
class Answers:
    disk: Disk
    desktop: str = "dwm"
    encryption: str = "none"
    cpu: str = "x86-64-v1"
    hostname: str = "vfos"
    username: str = "user"
    locale: str = "en_US.UTF-8"
    keyboard: str = "us"
    timezone: str = "UTC"

    def validate(self):
        if self.desktop not in ("dwm", "dwl") or self.encryption not in ("none", *KDFS) or self.cpu not in CPUS:
            raise Error("invalid desktop, encryption or CPU profile")
        if not re.fullmatch(r"/dev/[a-zA-Z0-9._/-]+", self.disk.path) or ".." in Path(self.disk.path).parts:
            raise Error("target must be an explicit /dev disk path")
        if self.disk.logical_sector not in (512, 4096) or self.disk.size < 8 * 1024**3:
            raise Error("installation requires at least 8 GiB and 512-byte or 4Kn logical sectors")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", self.hostname):
            raise Error("invalid hostname")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", self.username) or self.username in ("root", "seat", "nobody", "daemon", "bin", "sys"):
            raise Error("invalid or reserved username")
        if not re.fullmatch(r"[a-z]{2,3}_[A-Z]{2}\.UTF-8", self.locale):
            raise Error("locale must be of the form en_US.UTF-8")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", self.keyboard):
            raise Error("invalid console keyboard map")
        if not re.fullmatch(r"[a-zA-Z0-9_+/-]+", self.timezone) or ".." in Path(self.timezone).parts or self.timezone.startswith("/"):
            raise Error("invalid timezone")


def partition_path(disk, number):
    return disk + ("p" if disk[-1].isdigit() else "") + str(number)


def layout(disk: Disk):
    sector = disk.logical_sector
    if sector not in (512, 4096):
        raise Error("unsupported logical sector size")
    esp_mib = 36 if sector == 512 else 260
    first = MIB // sector
    root_start = (2 + esp_mib) * MIB // sector
    # Leave space for the backup GPT and round down to a MiB boundary.
    end = ((disk.size // sector - 34) // first) * first
    if end <= root_start:
        raise Error("disk is too small")
    return [{"number": 1, "start": first, "size": first, "type": "21686148-6449-6e6f-744e-656564454649", "name": "BIOS boot"},
            {"number": 2, "start": 2 * first, "size": esp_mib * first, "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "name": "EFI system"},
            {"number": 3, "start": root_start, "size": end - root_start, "type": "0fc63daf-8483-4772-8e79-3d69d8477de4", "name": "VFOS root"}]


def partition_script(disk):
    return ("label: gpt\nunit: sectors\n\n" + "\n".join(
        f'start={p["start"]}, size={p["size"]}, type={p["type"]}, name="{p["name"]}"' for p in layout(disk)) + "\n").encode()


def plan(answers):
    answers.validate()
    return {"answers": asdict(answers), "disk_identity": answers.disk.token, "partitions": layout(answers.disk),
            "root_filesystem": "xfs", "xfs_options": XFS_OPTIONS, "esp_mount": "/efi", "boot_on_root": True,
            "kdf_options": KDFS.get(answers.encryption), "swap": None,
            "steps": ["verify offline packages and release qualification", "recheck disk identity and mounted descendants",
                      "require typed final confirmation", "write GPT", "format ESP", "format/open LUKS2" if answers.encryption != "none" else "select plain root",
                      "format XFS", "mount target", "install selected package closure", "configure accounts and seat membership",
                      "create private random keyslot" if answers.encryption != "none" else "configure root mount",
                      "generate initramfs", "install BIOS, EFI32 and EFI64 GRUB", "unmount and close mappings"]}


def inventory(run=subprocess.run):
    result = run(["lsblk", "--json", "--bytes", "--paths", "--output", "PATH,TYPE,SIZE,LOG-SEC,SERIAL,MAJ:MIN,MODEL,MOUNTPOINTS,RO"],
                 check=True, capture_output=True, text=True)
    devices = json.loads(result.stdout)["blockdevices"]
    disks = []

    def busy(node):
        if any(node.get("mountpoints") or []):
            return True
        # Mapped devices (crypt/LVM/RAID), mounted or not, are in use.
        return any(c.get("type") != "part" or busy(c) for c in node.get("children", []))

    for node in devices:
        if node["type"] != "disk" or node.get("ro") or busy(node):
            continue
        disks.append(Disk(node["path"], int(node["size"]), int(node["log-sec"]), node.get("serial") or "",
                          node["maj:min"], (node.get("model") or "").strip()))
    return disks


class Runner:
    def __init__(self, progress=lambda message: None):
        self.progress = progress

    def __call__(self, argv, secret=None, input=None, capture=False):
        # Never echo arguments or subprocess stderr; cryptsetup errors can contain
        # sensitive input. Commands carry secrets only through anonymous stdin.
        self.progress(Path(argv[0]).name)
        result = subprocess.run(argv, input=secret if secret is not None else input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise Error(f"{Path(argv[0]).name} failed with exit code {result.returncode}; target is not complete")
        return result.stdout.decode().strip() if capture else None


def load_media(media: Path, answers):
    from .release import require_qualified
    data = json.loads((media / "manifest.json").read_text())
    require_qualified(data, answers.cpu)
    if data["cpu"] != answers.cpu:
        raise Error("offline media CPU profile differs from the selected profile")
    names = data["closures"][answers.desktop]
    packages = []
    try:
        seen = {}
        for name in names:
            entry = data["packages"][name]
            filename = entry["file"]
            if Path(filename).name != filename:
                raise Error("invalid offline package filename")
            package = Package(media / "packages" / filename, entry["sha256"])
            packages.append(package)
            if package.meta["name"] != name or package.meta["cpu"] != answers.cpu or package.meta.get("development_only", True):
                raise Error("invalid offline package provenance")
            if any(seen.get(dep) != abi for dep, abi in package.meta.get("dependencies", {}).items()):
                raise Error("offline package closure is missing dependencies or is out of order")
            seen[name] = package.meta["abi"]
        # Detect file conflicts and missing userspace inputs while still offline,
        # before any partitioning command can run.
        with tempfile.TemporaryDirectory(prefix="vfos-preflight-") as directory:
            staged = Path(directory)
            db = Database(staged)
            for package in packages:
                db.install(package)
            for executable in ("usr/bin/python3", "usr/bin/bash", "usr/bin/localedef", "usr/sbin/useradd",
                               "usr/sbin/groupadd", "usr/sbin/chpasswd", "usr/bin/dracut",
                               "usr/bin/grub-mkimage", "usr/sbin/grub-bios-setup", "usr/sbin/efibootmgr"):
                p = resolve_target(staged, executable)
                if not p.is_file() or not p.stat().st_mode & 0o111:
                    raise Error(f"missing installer executable in offline closure: {executable}")
            if not (staged / "usr/share/zoneinfo" / answers.timezone).is_file():
                raise Error("selected timezone is absent from offline packages")
        return data, packages
    except BaseException:
        for package in packages:
            package.close()
        raise


def write(root, name, content, mode=0o644):
    from .common import under
    p = under(root, name)
    if p.is_symlink():
        raise Error(f"refusing configuration symlink: {name}")
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    p.chmod(mode)


def configure(root, a, root_uuid, luks_uuid, run, account_password, root_password):
    write(root, "etc/hostname", a.hostname + "\n")
    write(root, "etc/hosts", f"127.0.0.1 localhost\n::1 localhost\n127.0.1.1 {a.hostname}\n")
    write(root, "etc/locale.conf", "LANG=" + a.locale + "\n")
    write(root, "etc/vconsole.conf", "KEYMAP=" + a.keyboard + "\n")
    zone = root / "usr/share/zoneinfo" / a.timezone
    if not zone.is_file():
        raise Error(f"timezone not present in installed packages: {a.timezone}")
    write(root, "etc/timezone", a.timezone + "\n")
    localtime = root / "etc/localtime"
    localtime.unlink(missing_ok=True)
    localtime.symlink_to("../usr/share/zoneinfo/" + a.timezone)
    write(root, "etc/vfos/profile", a.cpu + "\n")
    write(root, "etc/vfos/desktop", a.desktop + "\n")
    esp_uuid = run(["blkid", "-s", "UUID", "-o", "value", partition_path(a.disk.path, 2)], capture=True)
    if not re.fullmatch(r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}", esp_uuid):
        raise Error("invalid ESP UUID")
    write(root, "etc/fstab", f"UUID={root_uuid} / xfs defaults 0 0\nUUID={esp_uuid} /efi vfat noauto,umask=0077 0 2\ntmpfs /tmp tmpfs nosuid,nodev,mode=1777 0 0\n")
    if luks_uuid:
        write(root, "etc/crypttab", f"root UUID={luks_uuid} /etc/cryptsetup-keys.d/root.key luks\n", 0o600)
    run(["chroot", str(root), "localedef", "-i", a.locale.split(".")[0], "-f", "UTF-8", a.locale])
    run(["chroot", str(root), "groupadd", "--force", "seat"])
    run(["chroot", str(root), "useradd", "-m", "-s", "/bin/bash", "-G", "seat", a.username])
    run(["chroot", str(root), "chpasswd"], secret=a.username.encode() + b":" + account_password + b"\n")
    run(["chroot", str(root), "chpasswd"], secret=b"root:" + root_password + b"\n")


def execute(a, media, confirmation, account_password, passphrase=None, run=None, root_password=None):
    a.validate()
    if confirmation != "ERASE " + a.disk.path:
        raise Cancelled("final confirmation did not match; no disks changed")
    if not account_password or any(c in account_password for c in (b"\n", b"\r", b"\0", b":")):
        raise Error("invalid account password")
    if not root_password or any(c in root_password for c in (b"\n", b"\r", b"\0", b":")):
        raise Error("a separate root account password is required for console administration")
    if a.encryption != "none" and (not passphrase or b"\0" in passphrase):
        raise Error("encryption requires a nonempty passphrase")
    if os.geteuid() != 0:
        raise Error("installation requires root from the live ISO")
    data, packages = load_media(media, a)
    run = run or Runner()
    mounted, mapper = [], False
    try:
        tools = ["sfdisk", "udevadm", "mkfs.fat", "mkfs.xfs", "mount", "umount", "blkid", "chroot"]
        if a.encryption != "none":
            tools += ["cryptsetup"]
        missing = [tool for tool in tools if not shutil.which(tool)]
        if missing:
            raise Error("missing live installer tools: " + ", ".join(missing))
        # Re-inventory immediately before the first write, including all descendants.
        current = {d.path: d for d in inventory()}.get(a.disk.path)
        if current is None or current.token != a.disk.token:
            raise Error("disk identity changed or target is in use; no disks changed")
        st = os.stat(a.disk.path)
        if not stat.S_ISBLK(st.st_mode) or f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}" != a.disk.major_minor:
            raise Error("target no longer refers to the selected block device")
        mapping = "vfos-install-" + a.disk.token[:12]
        if Path("/dev/mapper", mapping).exists():
            raise Error("installer mapping already exists; inspect it before retrying")
        run(["sfdisk", "--wipe", "always", "--wipe-partitions", "always", a.disk.path], input=partition_script(a.disk))
        run(["udevadm", "settle", "--timeout=30"])
        esp, partition = partition_path(a.disk.path, 2), partition_path(a.disk.path, 3)
        run(["mkfs.fat", "-F", "32", "-s", "1", "-n", "VFOS_EFI", esp])
        luks_uuid = None
        rootdev = partition
        if a.encryption != "none":
            run(["cryptsetup", "luksFormat", "--batch-mode", "--type", "luks2", "--cipher", "aes-xts-plain64", "--key-size", "512",
                 *KDFS[a.encryption], "--key-file", "-", partition], secret=passphrase)
            run(["cryptsetup", "open", "--key-file", "-", partition, mapping], secret=passphrase)
            mapper = True
            luks_uuid = run(["cryptsetup", "luksUUID", partition], capture=True)
            rootdev = "/dev/mapper/" + mapping
        run(["mkfs.xfs", "-f", *XFS_OPTIONS, rootdev])
        from .boot import uuid
        root_uuid = uuid(run(["blkid", "-s", "UUID", "-o", "value", rootdev], capture=True))
        if luks_uuid:
            luks_uuid = uuid(luks_uuid)
        directory = tempfile.mkdtemp(prefix="vfos-target-")
        root = Path(directory)
        try:
            run(["mount", rootdev, str(root)])
            mounted.append(root)
            db = Database(root)
            for package in packages:
                db.install(package)
            for p in ("efi", "dev", "proc", "sys", "run"):
                (root / p).mkdir(exist_ok=True)
            run(["mount", "-o", "umask=0077", esp, str(root / "efi")])
            mounted.append(root / "efi")
            for p in ("dev", "proc", "sys", "run"):
                run(["mount", "--rbind", "/" + p, str(root / p)])
                mounted.append(root / p)
                run(["mount", "--make-rslave", str(root / p)])
            configure(root, a, root_uuid, luks_uuid, run, account_password, root_password)
            if luks_uuid:
                keydir = root / "etc/cryptsetup-keys.d"
                keydir.mkdir(mode=0o700, exist_ok=True)
                keydir.chmod(0o700)
                key = keydir / "root.key"
                fd = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(os.urandom(64))
                # This is a random-key slot, never a second password or weaker password fallback.
                run(["cryptsetup", "luksAddKey", "--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "600000", "--key-file", "-", partition, str(key)], secret=passphrase)
            firmware = None
            fwsize = Path("/sys/firmware/efi/fw_platform_size")
            if fwsize.exists():
                firmware = "efi" + fwsize.read_text().strip()
            install_boot(run, root, a.disk.path, root_uuid, kernel_version(data["kernel_version"]), luks_uuid, firmware)
        finally:
            cleanup_errors = []
            for p in reversed(mounted):
                try:
                    run(["umount", "--recursive", str(p)])
                except Error as e:
                    cleanup_errors.append(str(e))
            if cleanup_errors:
                # Never recursively delete a mountpoint, including on failure.
                raise Error("could not unmount target; inspect mounts before reboot: " + directory)
            root.rmdir()
    finally:
        if mapper:
            run(["cryptsetup", "close", mapping])
        for package in packages:
            package.close()


class Dialog:
    def call(self, widget, title, text, *args):
        command = ["dialog", "--stdout", "--clear", "--title", title, widget, text, "20", "76", *args]
        result = subprocess.run(command, stdout=subprocess.PIPE)
        if result.returncode in (1, 255):
            raise Cancelled("installation cancelled")
        if result.returncode:
            raise Error(f"dialog failed ({result.returncode})")
        return result.stdout.decode().rstrip("\n")

    def menu(self, title, text, options):
        return self.call("--menu", title, text, "10", *[v for row in options for v in row])

    def password(self, title):
        first = self.call("--insecure" if False else "--passwordbox", title, "Enter password")
        second = self.call("--passwordbox", title, "Confirm password")
        if first != second or not first:
            raise Error("passwords are empty or do not match")
        return first.encode()


def wizard(media, preview=False):
    ui = Dialog()
    if not shutil.which("dialog"):
        raise Error("dialog is required for the ncurses installer")
    disks = inventory()
    if not disks:
        raise Error("no unused whole disks available")
    path = ui.menu("Target disk", "All data on the selected disk will be erased after final review.",
                   [(d.path, f"{d.size // 1024**3} GiB {d.model} {d.serial}") for d in disks])
    disk = next(d for d in disks if d.path == path)
    desktop = ui.menu("Desktop", "Choose one desktop closure", [("dwm", "XLibre / st / dmenu"), ("dwl", "Wayland / foot / dmenu-wl")])
    locale = ui.call("--inputbox", "Locale", "UTF-8 locale", "en_US.UTF-8")
    keyboard = ui.call("--inputbox", "Keyboard", "Console keyboard map", "us")
    timezone = ui.call("--inputbox", "Timezone", "IANA timezone", "UTC")
    hostname = ui.call("--inputbox", "Hostname", "Machine name", "vfos")
    username = ui.call("--inputbox", "Account", "Desktop username", "user")
    encryption = ui.menu("Encryption", "Encrypt root, home and /boot?", [("argon2id", "LUKS2 / Argon2id"), ("pbkdf2", "LUKS2 / PBKDF2"), ("none", "Unencrypted XFS")])
    profile = json.loads((media / "manifest.json").read_text())["cpu"]
    answers = Answers(disk, desktop, encryption, profile, hostname, username, locale, keyboard, timezone)
    review = plan(answers)
    if preview:
        ui.call("--msgbox", "Preview; no disk writes", json.dumps(review, indent=2))
        return review
    # Verify media before requesting secrets or final destructive consent.
    _, packages = load_media(media, answers)
    for p in packages:
        p.close()
    password = ui.password("Desktop account password")
    root_password = ui.password("Root console administration password")
    passphrase = ui.password("Disk passphrase") if encryption != "none" else None
    confirm = ui.call("--inputbox", "Final review", f"{disk.path} {disk.model} {disk.size // 1024**3} GiB\n{profile}; {desktop}; {encryption}\n{username}@{hostname}; {locale}; {keyboard}; {timezone}\nGPT: BIOS 1 MiB, ESP {36 if disk.logical_sector == 512 else 260} MiB, XFS root remainder.\nType ERASE {disk.path} to destroy all data.")
    gauge = subprocess.Popen(["dialog", "--title", "Installing VFOS", "--gauge", "Preparing", "10", "76", "0"], stdin=subprocess.PIPE)
    progress_count = 0
    def progress(message):
        nonlocal progress_count
        progress_count = min(95, progress_count + 2)
        gauge.stdin.write(f"XXX\n{progress_count}\n{message}\nXXX\n".encode())
        gauge.stdin.flush()
    try:
        execute(answers, media, confirm, password, passphrase, Runner(progress), root_password)
        gauge.stdin.write(b"XXX\n100\nComplete\nXXX\n")
        gauge.stdin.flush()
    finally:
        gauge.stdin.close()
        gauge.wait()
    ui.call("--msgbox", "Installation complete", "Remove installation media and reboot. Log in on a console, then run vfos-session " + desktop + ".")
    return review
