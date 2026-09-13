from __future__ import annotations

import itertools
import json
from pathlib import Path

from .common import CPUS, Error, identity

CHECKS = {"install", "reboot", "layout", "fallback_loaders", "ordinary_user_seatd", "hotplug", "vt_switch", "logout_restart",
          "browser", "audio", "network", "source_rebuild", "kernel_update", "shutdown", "secret_scan", "cancel_before_write"}
CRYPT_CHECKS = {"wrong_passphrase_retry", "one_prompt", "encrypted_boot", "rescue", "keyslot_audit"}


def matrix():
    return [{"cpu": cpu, "firmware": firmware, "encryption": encryption, "desktop": "dwm" if i % 2 == 0 else "dwl",
             "logical_sector": 4096 if i % 3 == 2 else 512,
             "qemu_cpu": "qemu64" if cpu == "x86-64-v1" else "Haswell-noTSX",
             "memory_mib": 2048, "id": f"{cpu}-{firmware}-{encryption}"}
            for i, (cpu, firmware, encryption) in enumerate(itertools.product(CPUS, ("bios", "efi32", "efi64"), ("none", "pbkdf2", "argon2id")))]


def require_qualified(manifest, cpu):
    """A candidate cannot authorize an installation by claiming a boolean pass."""
    if manifest.get("status") != "qualified" or manifest.get("development_only", True):
        raise Error("release is unqualified: bootstrap, filesystem/firmware and desktop tests must pass before disk installation")
    inputs = manifest.get("input_id")
    if not inputs or inputs != identity(manifest.get("inputs", {})):
        raise Error("release input identity is missing or mismatched")
    for field in ("cpu", "packages", "closures", "kernel_version"):
        if manifest.get(field) is None or manifest["inputs"].get(field) != manifest[field]:
            raise Error(f"release evidence does not cover {field}")
    by_id = {r["id"]: r for r in manifest.get("qualification", [])}
    for case in matrix():
        if case["cpu"] != cpu:
            continue
        row = by_id.get(case["id"], {})
        required = CHECKS | (CRYPT_CHECKS if case["encryption"] != "none" else set())
        if row.get("input_id") != inputs or not all(row.get("checks", {}).get(c) is True for c in required):
            raise Error(f"missing current qualification evidence: {case['id']}")
        if row.get("desktop") != case["desktop"] or row.get("logical_sector") != case["logical_sector"]:
            raise Error(f"qualification case does not match matrix: {case['id']}")


def readiness(repo, config):
    groups = json.loads((config / "system.json").read_text())
    needed = set()
    for name, entries in groups.items():
        if name == "opt-in":
            continue
        if isinstance(entries, dict):
            needed.update(n for values in entries.values() for n in values)
        else:
            needed.update(entries)
    missing = needed - repo.recipes.keys()
    # Include missing transitive build and runtime requirements in the report.
    seen = set()
    pending = list(needed & repo.recipes.keys())
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for dep in repo.get(name).dependencies:
            if dep not in repo.recipes:
                missing.add(dep)
            else:
                pending.append(dep)
    release = json.loads((config / "release.json").read_text())
    return {"ready": not missing and release["status"] == "qualified", "available_recipes": sorted(repo.recipes),
            "missing_recipes": sorted(missing), "release": release}
