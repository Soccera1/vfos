# Implementation status

This was implemented in an empty repository. The whole distribution plan is not
complete. No VFOS ISO has been produced, no physical disk has been modified, and
no graphical/firmware/encryption boot test is reported as passed.

## Implemented

- Python CLI and shell recipe format with inert JSON headers; dependency ordering,
  cycle/missing-recipe diagnostics and external recipe overrides.
- HTTPS downloads pinned by SHA256, offline cache use, no-network bubblewrap
  builds, CPU-specific compiler flags and artifact directories, deterministic
  archives, provenance, file validation and declared dependency installation.
- Package ownership, conflicts, modified configuration preservation, dependency
  checks, transitive ABI rebuild queues, explicit rebuild command and recovery
  journals. Unit tests inject failures and simulate interrupted transactions.
- Real pinned recipes: GNU hello, seatd, XLibre, GRUB, xfsprogs, dwm, st and dmenu. Local
  recipes package the Python tools and session launchers. Recipes with missing
  dependencies fail dependency planning; they have not been compiled here.
- Installer dialog controller; pure layout planning for 512-byte and 4Kn disks;
  final typed erase confirmation; mounted-device/mapper filtering; identity
  recheck; offline package preflight; secrets on stdin; cleanup paths.
- Candidate disk execution, LUKS2/keyslot, dracut, BIOS/EFI32/EFI64 boot code;
  kernel update code that writes a temporary initramfs on root before switching
  the boot menu. These are unit-tested controllers, not boot-qualified systems.
- Session-scoped PipeWire/WirePlumber/Pulse compatibility; libseat seatd backend;
  non-root console launch; controlling-terminal XLibre invocation; descendant
  cleanup. SysVinit seatd service configures a root:seat 0660 socket.
- Kernel protection/mixed-EFI config fragment, desktop/network/logging config,
  and Firefox candidate compile/runtime policies with limitations documented.
- The 18-case CPU/firmware/encryption matrix, qualification contract, candidate
  ISO assembler, CI tooling tests and real GNU package smoke builds.

## Remaining work before an installable release

1. Implement and test VFOS-owned cross-toolchain, temporary userspace and native
   bootstrap handoffs. `vfos bootstrap` is a diagnostic gate, not an implemented
   bootstrap pipeline.
2. Complete every dependency recipe listed by `vfos status`, including GNU base,
   kernel, Mesa, firmware, microcode, networking, audio, Wayland and development
   tools. Pin every source and add ABI-compatible XLibre libinput packaging.
3. Package the base overlay: rcS/rc services, eudev ordering, asynchronous network
   start, bounded logging, user/group/filesystem setup. Present config files do
   not by themselves constitute an installed base system.
4. Test pinned xfsprogs 7.0.1 with GRUB 2.14. Qualify the proposed Argon2 costs on BIOS
   and EFI32. Test core embedding budget, unlock retry, one prompt, random-key
   slot handling, initramfs updates and rescue. Add extant upstream GRUB fixes
   only after identifying the relevant compatibility issues.
5. Complete dwl/wlroots/foot/dmenu-wl recipes and the dmenu-wl_run binding; package
   desktop configuration for editing/rebuilding. Test both display servers as
   ordinary users, hotplug, VT switching, graphics release and repeated logout.
6. Pin Firefox and its Rust/LLVM/GTK/media closure. Validate the candidate
   mozconfig, maintain source-removal patches, and test rendering/Wasm/media,
   extensions, devtools, policies and sandboxing. Measure actual savings.
7. Implement the live-root dracut module and offline media manifest production.
   The current ISO assembler expects these verified inputs. Test optical and
   direct-USB boot, fallback loaders, and sector-size support.
8. Add a candidate-image test path before qualification (the current installer
   deliberately accepts qualified media only), a QEMU driver for real ncurses
   installation and boot assertions, and the complete staged Actions pipeline
   with measured build batches and verified artifact/cache transfers. Unit tests
   exercise all matrix layouts; they are not firmware tests.
9. Finish automatic ABI rebuild integration into source upgrade transactions.
   Currently upgrades persist a rebuild queue and `pkg rebuild` processes it;
   images reject pending rebuilds. Dependency constraints are ABI identifiers,
   not a general version solver. Empty directories are not package-owned yet.
10. Test physical Intel/AMD hardware, suspend/resume and controlled responsiveness,
    startup, idle-activity and memory workloads using the resulting CI images.

Deferred by design: proprietary NVIDIA, multilib, Secure Boot enrollment,
hibernation, unencrypted disk swap and automated dual-OS installation.

The release gate stays unqualified until these prerequisites and evidence are
present. Routine Actions runs publish readiness reports; manual `require_ready`
enforces the release gate. Changing the status field alone does not satisfy the
evidence checker.
