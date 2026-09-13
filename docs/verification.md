# Verification performed

Local validation on 2026-09-13:

| Check | Result |
|---|---|
| Python unit suite | 46 passed |
| Recipe metadata and shell syntax | 10 recipes passed |
| JSON configuration syntax | Passed |
| Upstream source archive checksums | All 8 matched recipe pins |
| GNU hello v1 isolated build | Passed; 6 upstream tests passed, 1 locale test skipped |
| GNU hello v3 isolated build | Passed; 6 upstream tests passed, 1 locale test skipped |
| Package install / execute / verify / remove | Passed for both CPU profiles |
| XFS option validation | Accepted by host xfsprogs 7.0.1 in no-write mode |
| FAT32 ESP formatting | 36 MiB/512-byte and 260 MiB/4Kn disposable files, no warnings |
| CLI installation plan | Rendered without disk probing or writes |
| Release readiness | Correctly rejected as incomplete/unqualified |

The package build tests use the explicitly marked development host seed inside
bubblewrap; they are not a VFOS cross-toolchain bootstrap. The maintained GNU
hello patch parenthesizes three gnulib declarations to handle the host glibc's
function-like C23 macros. Neither compiler protections nor its upstream tests
were disabled to get a passing build.

Source archives and generated development packages/logs are under ignored
`cache/` and `out/`. CI repeats source download verification and package tests on
pinned Ubuntu 24.04 runners. The checkout is connected to the public
`Soccera1/vfos` repository. Hosted Actions verification is pending the initial
push. Local actionlint v1.7.7 validation passed; a nested Ubuntu container ran
the unit suite but could not mount a nested `/proc` for bubblewrap. This is not
a successful Ubuntu source-build result.

**Not run:** kernel bootstrap, GRUB builds/boot, installer writes to disks,
EFI32/EFI64/BIOS boots, LUKS unlock, full desktop/browser/audio/network sessions,
hardware suspend/resume, performance measurements or ISO assembly. The 18-case
matrix is a specification; only its layout calculations have been exercised.
