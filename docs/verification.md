# Verification performed

Validation on 2026-09-13:

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
`cache/` and `out/`. Hosted verification passed on the public
[Soccera1/vfos repository](https://github.com/Soccera1/vfos):

- [Successful development workflow](https://github.com/Soccera1/vfos/actions/runs/34732987452)
  at commit `8b0f722`: 46 unit tests, workflow linting, both unprivileged source
  builds, upstream tests and both fresh-runner download/install/execute/verify/
  remove checks passed.
- [Readiness report](https://github.com/Soccera1/vfos/actions/runs/34732987507)
  correctly reports the remaining distribution work without blocking development.
- Five nonempty artifacts were uploaded: tooling validation, two development
  packages and two independent verification reports. The downloaded archives'
  hashes were compared with the indices and verification reports; both matched.

The initial hosted attempt identified an AppArmor namespace restriction. A
path-specific userns profile for a root-owned CI-only bubblewrap copy resolved
it; global AppArmor/sysctl settings were not disabled. Local actionlint v1.7.7
validation also passed. An earlier nested Ubuntu container could not mount
nested `/proc`; the actual hosted runs above establish Ubuntu runner behavior.

**Not run:** kernel bootstrap, GRUB builds/boot, installer writes to disks,
EFI32/EFI64/BIOS boots, LUKS unlock, full desktop/browser/audio/network sessions,
hardware suspend/resume, performance measurements or ISO assembly. The 18-case
matrix is a specification; only its layout calculations have been exercised.
