# Development CI

`Validate tooling` runs on pull requests, pushes to `main`/`master`, and manual
workflow dispatch. It does useful work before the distribution is release-ready:

1. Lint GitHub workflow syntax/expressions and run the Python suite and recipe
   validation. Upload test logs, the proposed boot matrix and readiness data.
2. On separate Ubuntu 24.04 x64 runners, build pinned GNU hello from verified
   source for x86-64-v1 and x86-64-v3. Check runner CPU/disk capacity before build.
   The normal VFOS builder runs unprivileged in bubblewrap without build-network
   access; its upstream tests must pass. Record GNU time resource measurements.
3. Write `smoke.json`, an explicit archive path, expected SHA256, CPU profile,
   build-input identity and source pins. Upload it with the package, source/build
   manifests and logs as `development-package-CPU`.
4. Fresh runners download those artifacts. Verify against the recorded checksum
   and build identity, then install into a private temporary root, execute the
   installed binary, verify owned files and remove it. Upload the verification
   report as `verified-package-CPU`, also showing the result in the job summary.

The smoke package is marked development-only. It cannot become a release package
by being uploaded/downloaded. This CI does not claim to bootstrap VFOS, produce
an ISO or test firmware/desktops/encryption. A green development workflow means
these actual tooling/build/transfer checks passed.

`Development readiness` produces machine-readable and Markdown reports and a job
summary on default-branch pushes and manual dispatch. Missing distro components
are expected at this stage. To explicitly enforce release readiness, dispatch
with `require_ready=true`; the job then fails while release requirements are
unmet. Installer and image qualification gates are unchanged.

All external Actions use full commit pins. actionlint uses a fixed Go module
version, authenticated by the Go checksum database. Build artifacts are not
restored from broad caches. Each job records current build inputs, and each
matrix lane has a separate artifact name. No repository publishing permissions,
secrets, live disks or privileged source-build steps are required.

Local equivalents, from the checkout, using an unprivileged user:

```sh
python3 -m unittest discover -s tests -v
./bin/vfos validate
python3 ci/resources.py --cpu x86-64-v1
python3 ci/build-smoke.py --cpu x86-64-v1 --output out/ci-v1
python3 ci/package-smoke.py --manifest out/ci-v1/smoke.json --cpu x86-64-v1
python3 ci/check-release.py
python3 ci/check-release.py --require-ready  # expected to fail until qualified
```

Repeat the build and verification commands with `x86-64-v3` on a capable CPU.
`--offline` on the build command requires sources already present in `cache/`.
The build script selects the returned archive directly, so stale build artifacts
cannot accidentally enter the test through a wildcard.

Ubuntu 24.04 restricts unprivileged user namespaces using AppArmor. The runner setup script installs a root-owned CI-only bubblewrap copy and loads
a path-specific, userns-enabled AppArmor profile for it. The initial hosted run
showed that installing the packages alone was insufficient (RTM_NEWADDR was
denied). This setup does not disable AppArmor or globally relax host sysctls.
A namespace probe must pass before source downloads or builds begin. See [Ubuntu's explanation](https://discourse.ubuntu.com/t/understanding-apparmor-user-namespace-restriction/58007).
