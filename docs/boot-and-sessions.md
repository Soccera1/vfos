# Boot, installation and sessions

The GPT layout starts at 1 MiB and reserves 1 MiB for BIOS embedding. The ESP
starts at 2 MiB and uses 36 MiB on 512-byte logical sectors or 260 MiB on 4Kn.
It is explicitly FAT32 with one logical sector per cluster; both sizes have been
formatted successfully as disposable files. Root starts immediately after it,
with space retained for the backup GPT. Disk writes require whole-device
selection, matching typed confirmation and a fresh identity/in-use check.
The account screens collect separate desktop and root-console passwords; the
latter permits local administration without running the graphical session as root.

Root is XFS; `/home` and `/boot` stay on it. The candidate XFS contract retains
metadata CRCs and disables newer optional features until GRUB compatibility is
qualified. `ci/filesystem-smoke.py` validates argument shapes and the ESP sizing
without touching a block device. This is not a GRUB compatibility test.

GRUB 2.14 is pinned. Its source contains the Argon2 and LUKS2 modules. This does
not establish that the BIOS core will fit or that each firmware can unlock the
selected costs. Every target embeds GPT, XFS and necessary cryptographic modules;
the BIOS core has a size check before setup. Both EFI fallback filenames are
written; matching NVRAM registration is attempted on EFI. The current controller
reports an efibootmgr failure even though fallback files may already be usable.

Encryption selects AES-XTS with a 512-bit key. The candidate Argon2id preset is
64 MiB, four iterations and one lane. PBKDF2 is separately selectable at 600,000
iterations. These values are explicit test candidates, **not hardware-qualified
cost recommendations**. There is no automatic password fallback slot.

The installer creates a fresh 64-byte random key on encrypted root, mode 0600
inside a 0700 directory. Its separate PBKDF2 keyslot is for high-entropy random
key material, not a weakened copy of the user's password. The key is included in
the initramfs stored on encrypted `/boot`, never in GRUB's unencrypted image or
the ESP. The initial GRUB config contains one unlock loop; the menu does not
prompt again. Dracut reads crypttab and the embedded key to reopen root.

`vfos update-kernel --version VERSION` checks the root and key arrangement,
builds a temporary initramfs on root, preserves the previous image, then changes
the GRUB menu. A failed dracut leaves the prior boot image/menu intact. Test this
with every boot mode before making the installer available on real machines.

Rescue requires the user's passphrase: open the root partition with cryptsetup,
mount it, bind the live `/dev`, `/proc`, `/sys` and `/run`, then use the installed
kernel-update command in a chroot. Do not copy its key or initramfs to the ESP.
There is no unencrypted disk swap or hibernation configuration.

Both desktop launchers force `LIBSEAT_BACKEND=seatd`. The shared service starts
seatd as root with the `seat` socket group, then tightens its upstream 0770 socket
to 0660. Installer-created desktop users join `seat`. XLibre uses modesetting and
libinput, with logind, the setuid wrapper, nested/test servers and TCP listening
disabled. Its X server invocation retains the console terminal with `-keeptty`.

The session supervisor uses a private 0700 runtime directory, a per-session D-Bus
bus, minimal audio processes and Linux subreaper support. On logout it terminates
session descendants, including orphaned applications, without signalling every
process owned by the user. These semantics need live tests with browsers that
daemonize, multiple logins and abrupt VT/session termination.

Upstream references checked during implementation:

- [XLibre 25.1.6 build options](https://github.com/X11Libre/xserver/blob/xlibre-xserver-25.1.6/meson_options.txt)
- [XLibre seatd startup documentation](https://github.com/X11Libre/xserver/blob/xlibre-xserver-25.1.6/README.md)
- [seatd 0.9.1 build options](https://github.com/kennylevinsen/seatd/blob/0.9.1/meson_options.txt)
- [seatd socket implementation](https://github.com/kennylevinsen/seatd/blob/0.9.1/seatd/seatd.c)
- [GRUB 2.14 release announcement](https://lists.gnu.org/archive/html/grub-devel/2026-01/msg00029.html)
