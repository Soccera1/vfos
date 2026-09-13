# Source and package model

Each `recipes/NAME/recipe.sh` has a JSON metadata header on its second line.
Headers declare name, version, ABI, runtime/build dependencies, HTTPS sources with
SHA256, patches and optional local source files. Planning parses JSON without
executing the shell. Recipes provide `prepare`, `build`, `check`, and `stage`;
staging writes to `$DESTDIR`. Declared patches enter the fingerprint and are
applied explicitly by `prepare`. Meson wraps/downloads are disabled.

Recipes are trusted executable code. Read-only build roots, private build/home
and temporary directories, a fresh environment and a disabled network limit
accidental host contamination. The development host seed is explicitly marked;
production requires a VFOS package-owned builder root and declared dependency
artifacts. Package payloads never execute privileged install hooks.

`local_files` is an explicit mapping from checkout-relative input files to paths
under `$RECIPE_DIR`. These files, recipe bytes and patches enter the build hash.
Source SHA256, dependency archive hashes, CPU/flags, jobs, builder identity and
Python engine hashes also enter it. Native builders are checked against their
package database. Host-seed provenance is diagnostic, not a reproducible trusted
compiler bootstrap. Build IDs change when inputs change; a cached package is
verified against its saved hash receipt before reuse.

Downloads use TLS plus pinned checksums. The committed checksums were computed
from the selected upstream archives, not invented. This is not a claim of
independent cryptographic release-signature verification. Updating a source pin
requires review; public signatures and a maintained trust-key policy remain to
be added before distribution releases.

A `.pkg.tar.xz` holds `manifest.json` and `root/` payload entries with normalized
archive timestamps and ownership. The manifest records hashes, modes, links,
ABIs, profile and build provenance. The reader rejects duplicate/unlisted entries,
path traversal, unsafe ancestors, devices, hardlinks and setuid/setgid payloads.
Symlinks may represent normal target-root links but are never followed during
installation. Package source extraction additionally uses Python's data filter.

The package database is under `var/lib/vfos/state` within the selected root.
An advisory lock serializes changes. Each transaction first makes durable
preimages and a journal, then updates files and atomically replaces metadata.
An uncommitted transaction rolls back on reopen; a committed journal is cleaned
up. Recovery assumes a private target tree: do not concurrently modify its
filesystem outside the package manager. Empty parent directories can remain
after removal. Package-owned empty directories and general ownership metadata
are not yet represented in the archive format.

A changed `/etc` file retains its previous baseline hash so verification still
reports local edits. An upgrade's new default goes to `.vfos-new`; resolve an
existing candidate before the next changed default. Removal retains edited
configuration. Nonconfiguration package files are replaced during upgrades.

`pkg sync --url HTTPS_SNAPSHOT --sha256 HASH` consumes a tar snapshot containing
`recipes/`. Overrides must be outside it; the old tree is retained as `.previous`.
This local snapshot switch is not yet journalled against a machine crash between
renames. Sync does not pull or execute a moving Git branch. Override recipes that
use `local_files` must carry those files alongside their own repository layout.

The package checksum supplied to `pkg install` must come from a trusted manifest.
A checksum is integrity, not publisher authentication. No artifact signing or
public mirror is configured in this initial repository.
