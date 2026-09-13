# Firefox trimming status

There is no buildable/pinned Firefox recipe yet. `config/firefox/mozconfig` is a
candidate, and `policies.json` is runtime policy input. They must be validated
against the eventual pinned source; unsupported preferences can silently do
nothing. No resource-saving or code-removal claim is made from these files.

Compile-time candidates disable the independent updater, crash reporter, tests,
debug artifacts and auxiliary platform services. They retain normal browser
rendering, JavaScript/Wasm, media, extensions, developer tools and sandboxing.
Individual configure options must be checked against the selected release.

Telemetry/studies, accounts/sync, sponsored content and ML/chat are currently
represented by policies/preferences. **Runtime disabling is not source removal.**
Maintained patches and resulting dependency/size reductions remain work to do.
AI features change quickly; inspect the selected policy schema and source, test
`about:policies`, then verify network requests and the relevant UI. The current
candidate does not promise coverage of every future AI integration.

Do not disable the process sandbox, seccomp, site isolation, certificate checking
or kernel mitigations in pursuit of trimming. Do not pass `MOZ_DISABLE_CONTENT_SANDBOX`
or enable root browser execution. LTO/PGO need package-specific measurements for
both CPU profiles, including build-resource limits on hosted runners.

Acceptance: static/dynamic pages, Canvas/WebGL, Wasm, a supported video/audio
corpus, extensions, devtools and both X11/Wayland sessions. Record idle CPU and
wakeups, memory/PSS, startup and interaction timings against the same baseline,
hardware, browser profile and workload. Check that unwanted services are absent
while security and ordinary media behavior remain intact.

[Mozilla's policy source](https://github.com/mozilla/policy-templates) and the
[Firefox administrator reference](https://firefox-admin-docs.mozilla.org/) provide
the policy contract. Policy files alone are not a heavily trimmed Firefox build.
