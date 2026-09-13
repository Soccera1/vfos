#!/bin/bash
# Configure only an ephemeral GitHub-hosted Ubuntu build runner.
set -euo pipefail
if [[ ${GITHUB_ACTIONS:-} != true || ${RUNNER_ENVIRONMENT:-} != github-hosted ]]; then
    echo 'This setup script is only for ephemeral GitHub-hosted runners.' >&2
    exit 1
fi
sudo apt-get update
sudo apt-get install -y bubblewrap build-essential gettext texinfo patch apparmor

# Ubuntu's restricted-unprivileged-userns policy can strip the capabilities
# bwrap needs to set up its private network. Attach a userns-enabled profile to
# a root-owned CI-only copy; leave global sysctls and other profiles unchanged.
ci_bin=/usr/local/libexec/vfos-ci
sudo install -d -m 0755 "$ci_bin"
sudo install -m 0755 /usr/bin/bwrap "$ci_bin/bwrap"
if [[ -r /sys/module/apparmor/parameters/enabled ]] && [[ $(cat /sys/module/apparmor/parameters/enabled) == Y ]]; then
    sudo tee /etc/apparmor.d/vfos-ci-bwrap >/dev/null <<'PROFILE'
abi <abi/4.0>,
include <tunables/global>
profile vfos-ci-bwrap /usr/local/libexec/vfos-ci/bwrap flags=(unconfined) {
    userns,
}
PROFILE
    sudo apparmor_parser --replace /etc/apparmor.d/vfos-ci-bwrap
fi
printf '%s\n' "$ci_bin" >> "$GITHUB_PATH"
# Fail during setup, before downloads, if the runner still cannot isolate builds.
"$ci_bin/bwrap" --unshare-all --die-with-parent --ro-bind / / -- /usr/bin/true
