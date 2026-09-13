from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .common import CPUS, Error, atomic_json, digest
from .recipes import Repository
from .packages import Database, Package


def project_root():
    source = Path(__file__).resolve().parents[1]
    return source if (source / "profiles").exists() else Path("/usr/share/vfos")


def emit(data):
    print(json.dumps(data, indent=2, sort_keys=True))


def selected_cpu(value, root):
    profile = root / "etc/vfos/profile"
    inherited = profile.read_text().strip() if profile.exists() else None
    if inherited and inherited not in CPUS:
        raise Error("installed CPU profile is invalid")
    if value and inherited and value != inherited:
        raise Error("requested CPU differs from the installed system profile")
    return value or inherited or "x86-64-v1"


def sync(args):
    from .build import fetch, unpack
    source = {"url": args.url, "filename": "recipes.tar.xz", "sha256": args.sha256}
    import re
    if not source["url"].startswith("https://") or not re.fullmatch(r"[a-f0-9]{64}", args.sha256):
        raise Error("sync requires an HTTPS snapshot URL and exact SHA256")
    if args.overrides and (args.recipes.resolve() == args.overrides.resolve() or args.recipes.resolve() in args.overrides.resolve().parents):
        raise Error("overrides must be outside the synchronized tree")
    archive = fetch(source, args.cache / "snapshots")
    parent = args.recipes.resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent, prefix=".vfos-sync-") as td:
        temporary = Path(td)
        unpack(archive, temporary)
        incoming = temporary / "recipes"
        if not incoming.is_dir():
            raise Error("snapshot must contain a top-level recipes/ directory")
        Repository(incoming)
        backup = args.recipes.with_name(args.recipes.name + ".previous")
        if backup.exists():
            raise Error(f"previous snapshot backup exists: {backup}; review it before syncing again")
        if args.recipes.exists():
            args.recipes.rename(backup)
        try:
            incoming.rename(args.recipes)
        except BaseException:
            if backup.exists():
                backup.rename(args.recipes)
            raise
    emit({"snapshot_sha256": args.sha256, "recipes": str(args.recipes), "previous": str(backup)})


def parser():
    p = argparse.ArgumentParser(prog="vfos", description="VFOS source packages, installation and image tooling")
    p.add_argument("--recipes", type=Path, default=project_root() / "recipes")
    p.add_argument("--overrides", type=Path, default=Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "vfos/recipes")
    p.add_argument("--profiles", type=Path, default=project_root() / "profiles")
    sub = p.add_subparsers(dest="command", required=True)
    def cpu(command):
        command.add_argument("--cpu", choices=CPUS)
    def build_options(command):
        cpu(command)
        command.add_argument("--builder-root", type=Path)
        command.add_argument("--host-tools", action="store_true", help="development-only isolated host seed; cannot produce release packages")
        command.add_argument("--cache", type=Path, default=Path("cache"))
        command.add_argument("--output", type=Path, default=Path("out/packages"))
        command.add_argument("--jobs", type=int, default=2)
        command.add_argument("--offline", action="store_true")
    pkg = sub.add_parser("pkg")
    commands = pkg.add_subparsers(dest="pkg_command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("names", nargs="+")
    plan.add_argument("--runtime-only", action="store_true")
    build = commands.add_parser("build")
    build.add_argument("names", nargs="+")
    build_options(build)
    build.add_argument("--root", type=Path, default=Path("/"), help="inherit this system's CPU profile")
    for name in ("install", "upgrade"):
        command = commands.add_parser(name)
        command.add_argument("archive", type=Path)
        command.add_argument("--sha256", required=True, help="expected archive SHA256 from a trusted manifest")
        command.add_argument("--root", type=Path, required=True)
    for name in ("remove", "query", "verify", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        if name == "remove":
            command.add_argument("name")
    command = commands.add_parser("rebuild")
    command.add_argument("--root", type=Path, required=True)
    build_options(command)
    command = commands.add_parser("sync")
    command.add_argument("--url", required=True)
    command.add_argument("--sha256", required=True)
    command.add_argument("--cache", type=Path, default=Path("cache"))
    command = sub.add_parser("bootstrap")
    cpu(command)
    command.add_argument("--plan", action="store_true")
    command = sub.add_parser("image")
    cpu(command)
    command.add_argument("--root", type=Path)
    command.add_argument("--media", type=Path)
    command.add_argument("--output", type=Path)
    command.add_argument("--plan", action="store_true")
    command = sub.add_parser("install-system")
    command.add_argument("--media", type=Path, default=Path("/run/vfos/media"))
    command.add_argument("--plan", type=Path, metavar="ANSWERS_JSON", help="render a plan only; never accepts secrets")
    command.add_argument("--preview", action="store_true", help="ncurses preview with no writes")
    command = sub.add_parser("update-kernel")
    command.add_argument("--version", required=True)
    command.add_argument("--root", type=Path, default=Path("/"))
    sub.add_parser("status")
    sub.add_parser("test-matrix")
    sub.add_parser("validate")
    return p


def dispatch(a):
    if a.command == "update-kernel":
        from .kernel import update
        update(a.version, a.root)
        return
    if a.command == "install-system":
        from .installer import Answers, Disk, plan, wizard
        if a.plan:
            data = json.loads(a.plan.read_text())
            unknown = set(data) - set(Answers.__dataclass_fields__)
            if unknown:
                raise Error("unknown/sensitive fields in saved answers: " + ", ".join(sorted(unknown)))
            data["disk"] = Disk(**data["disk"])
            emit(plan(Answers(**data)))
        else:
            wizard(a.media, a.preview)
        return
    if a.command == "test-matrix":
        from .release import matrix
        emit(matrix())
        return
    if a.command == "pkg" and a.pkg_command == "sync":
        sync(a)
        return
    repo = Repository(a.recipes, a.overrides)
    if a.command in ("status", "validate"):
        from .release import readiness
        if a.command == "validate":
            for recipe in repo.recipes.values():
                recipe.fingerprint
                subprocess.run(["bash", "-n", str(recipe.path)], check=True)
            emit({"valid_recipe_headers": len(repo.recipes), "release_ready": readiness(repo, a.profiles)["ready"]})
        else:
            emit(readiness(repo, a.profiles))
        return
    if a.command == "bootstrap":
        from .bootstrap import bootstrap, bootstrap_plan
        emit((bootstrap_plan if a.plan else bootstrap)(repo, a.profiles, a.cpu or "x86-64-v1"))
        return
    if a.command == "image":
        from .release import readiness
        if a.plan:
            emit(readiness(repo, a.profiles))
            return
        if not all((a.root, a.media, a.output)):
            raise Error("image needs --root, --media and --output (or --plan)")
        from .image import image
        image(a.root, a.media, a.output, selected_cpu(a.cpu, a.root))
        return
    command = a.pkg_command
    if command == "plan":
        emit([{"name": r.name, "version": r.meta["version"], "inputs": r.fingerprint} for r in repo.plan(a.names, a.runtime_only)])
    elif command in ("build", "rebuild"):
        from .build import Builder
        builder = Builder(repo, selected_cpu(a.cpu, a.root), a.cache, a.output, a.builder_root, a.host_tools, a.jobs, a.offline)
        names = a.names if command == "build" else Database(a.root).query()["rebuild"]
        artifacts = builder.build(names)
        if command == "rebuild":
            for name in names:
                with Package(artifacts[name]) as package:
                    Database(a.root).install(package, upgrade=True)
        emit({name: str(path) for name, path in artifacts.items()})
    elif command in ("install", "upgrade"):
        with Package(a.archive, a.sha256) as package:
            if a.root.resolve() == Path("/") and package.meta.get("development_only", True):
                raise Error("development packages may only be installed into a disposable target root")
            pending = Database(a.root).install(package, upgrade=command == "upgrade")
        emit({"installed": package.meta["name"], "rebuild_required": pending})
    elif command == "remove":
        Database(a.root).remove(a.name)
        emit({"removed": a.name})
    elif command == "verify":
        result = Database(a.root).verify()
        emit(result)
        return 1 if result else 0
    else:
        emit(Database(a.root).query())  # query and recover both replay an interrupted journal


def main():
    try:
        result = dispatch(parser().parse_args())
        sys.exit(result or 0)
    except (Error, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as e:
        print(f"vfos: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("vfos: interrupted", file=sys.stderr)
        sys.exit(130)
