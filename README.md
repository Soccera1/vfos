# VFOS

VFOS is an early source-first GNU/Linux distribution project for a minimal developer
workstation. The target is two 64-bit CPU profiles, SysVinit, XFS with optional
LUKS2, and either dwm/XLibre or dwl, sharing libseat/seatd.

**This repository is not yet a bootable distribution.** It contains working
package tooling, installer/boot controllers and configuration, with explicit
release gates. Bootstrap, most dependency recipes, the live root, Firefox's
source integration and firmware/desktop qualification remain unfinished.
[Implementation status](docs/status.md) separates tested behavior from candidates.

From this checkout (Python 3.12+):

```sh
./bin/vfos validate
python3 -m unittest discover -s tests -v
./bin/vfos status
./bin/vfos test-matrix
./bin/vfos pkg plan hello
```

Build a real GNU package with verified downloads, no build network access, upstream
checks, deterministic packaging, and a log of complete recipe inputs:

```sh
./bin/vfos pkg build hello --cpu x86-64-v1 --host-tools
./bin/vfos pkg build hello --cpu x86-64-v3 --host-tools
```

These commands require an **unprivileged** Linux user, bubblewrap/user namespaces,
GCC, binutils, Make, patch, gettext and Texinfo. The v3 tests require a v3-capable
host. `--host-tools` marks every artifact as development-only; it cannot seed a
release image. Production builds use `--builder-root` with a verified VFOS native
builder. There is no host-distro package import path into release artifacts.

Install a package into a disposable directory using the checksum from the trusted
build receipt; `--root` is mandatory for package mutations:

```sh
./bin/vfos pkg install PATH.pkg.tar.xz --sha256 EXPECTED_SHA256 --root /tmp/vfos-root
./bin/vfos pkg query --root /tmp/vfos-root
./bin/vfos pkg verify --root /tmp/vfos-root
./bin/vfos pkg remove hello --root /tmp/vfos-root
```

`pkg upgrade` preserves edited `/etc` files and writes `.vfos-new` candidates.
ABI changes queue transitive dependents for `pkg rebuild`. `pkg recover` restores
an interrupted transaction; every other database operation also recovers first.
See [package format and trust boundaries](docs/packages.md).

`./bin/vfos install-system --plan tests/fixtures/install.json` renders the
partitioning plan without probing or writing a disk. The interactive command uses
`dialog`. Installation and image assembly reject unqualified media before disk
writes. `bootstrap --plan` lists the required VFOS-owned stages; `bootstrap`
currently reports the missing recipes instead of claiming to have bootstrapped.

GitHub Actions validates the tooling and builds GNU hello for both CPU profiles.
A separate runner downloads each build artifact, checks its recorded checksum and
provenance, then installs, executes, verifies and removes the package. Build logs,
source/package manifests, resource measurements and verification reports are
uploaded. Development readiness runs report remaining distribution work without
failing every push; manual `require_ready` enforcement still fails if a release
is incomplete. The workflows do **not** currently produce an ISO.
See [CI commands and artifacts](docs/ci.md).
