"""Bootstrap stage contracts; never substitute host distribution packages."""
from __future__ import annotations

import json
from pathlib import Path

from .common import Error


def bootstrap_plan(repo, profiles, cpu):
    stages = json.loads((profiles / "system.json").read_text())["bootstrap"]
    return {"cpu": cpu, "stages": [{"name": stage, "recipes": names,
             "missing": [n for n in names if n not in repo.recipes]} for stage, names in stages.items()],
            "isolation": "cross-toolchain -> temporary-userspace -> native-system",
            "host_distribution_packages_allowed": False}


def bootstrap(repo, profiles, cpu):
    plan = bootstrap_plan(repo, profiles, cpu)
    missing = [n for stage in plan["stages"] for n in stage["missing"]]
    if missing:
        raise Error("bootstrap cannot run: missing VFOS-owned stage recipes: " + ", ".join(missing))
    # Deliberately a hard gate until the cross -> native handoff is implemented
    # and qualified. A host-tools build is not a self-hosted bootstrap.
    raise Error("cross-to-native bootstrap handoff is not implemented; see docs/status.md")
