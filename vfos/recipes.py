from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from .common import Error, digest, identity

NAME = re.compile(r"[a-z0-9][a-z0-9+_.-]*\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True)
class Recipe:
    path: Path
    meta: dict

    @property
    def name(self):
        return self.meta["name"]

    @property
    def dependencies(self):
        return list(dict.fromkeys(self.meta.get("depends", []) + self.meta.get("build_depends", [])))

    @property
    def local_files(self):
        files = {}
        for origin, destination in self.meta.get("local_files", {}).items():
            for value in (origin, destination):
                if Path(value).is_absolute() or ".." in Path(value).parts:
                    raise Error(f"invalid local source path: {value}")
            source = self.path.parents[2] / origin
            if not source.is_file() or source.is_symlink():
                raise Error(f"local source is not a regular file: {source}")
            files[destination] = source
        return files

    @property
    def fingerprint(self):
        return identity({"recipe": digest(self.path), "metadata": self.meta,
                         "local_files": {p: digest(s) for p, s in self.local_files.items()},
                         "patches": {p: digest(self.path.parent / p) for p in self.meta.get("patches", [])}})


class Repository:
    """Metadata is data, never evaluated as shell during query or planning."""

    def __init__(self, path: Path, overrides: Path | None = None):
        self.path = path.resolve()
        self.recipes = {}
        for tree in (self.path, overrides):
            if tree is None or not tree.exists():
                continue
            if tree == overrides and (tree.resolve() == self.path or self.path in tree.resolve().parents):
                raise Error("overrides must be outside the synchronized recipe tree")
            for file in sorted(tree.glob("*/recipe.sh")):
                lines = file.read_text().splitlines()
                if len(lines) < 2 or not lines[1].startswith("# vfos: "):
                    raise Error(f"missing JSON recipe header: {file}")
                try:
                    meta = json.loads(lines[1][8:])
                except ValueError as e:
                    raise Error(f"invalid recipe metadata in {file}: {e}") from e
                for field in ("name", "version", "abi"):
                    if not isinstance(meta.get(field), str) or not NAME.fullmatch(meta[field]):
                        raise Error(f"invalid {field} in {file}")
                if meta["name"] != file.parent.name:
                    raise Error(f"recipe directory/name mismatch: {file}")
                for dep in meta.get("depends", []) + meta.get("build_depends", []):
                    if not isinstance(dep, str) or not NAME.fullmatch(dep):
                        raise Error(f"invalid dependency in {file}")
                for source in meta.get("sources", []):
                    if not HASH.fullmatch(source.get("sha256", "")):
                        raise Error(f"missing SHA256 pin in {file}")
                    if not source.get("url", "").startswith("https://"):
                        raise Error(f"sources must use HTTPS: {file}")
                    if not NAME.fullmatch(source.get("filename", "")):
                        raise Error(f"invalid source filename: {file}")
                for patch in meta.get("patches", []):
                    p = (file.parent / patch).resolve()
                    if file.parent.resolve() not in p.parents or not p.is_file():
                        raise Error(f"invalid patch: {patch}")
                for phase in ("prepare", "build", "check", "stage"):
                    if not re.search(rf"^{phase}\(\)\s*\{{", "\n".join(lines), re.M):
                        raise Error(f"missing {phase} function: {file}")
                self.recipes[meta["name"]] = Recipe(file, meta)

    def get(self, name):
        try:
            return self.recipes[name]
        except KeyError:
            raise Error(f"missing VFOS recipe: {name}") from None

    def plan(self, names, runtime_only=False):
        ordered, active, seen = [], [], set()

        def visit(name):
            if name in active:
                raise Error("dependency cycle: " + " -> ".join(active + [name]))
            if name in seen:
                return
            recipe = self.get(name)
            active.append(name)
            for dep in recipe.meta.get("depends", []) if runtime_only else recipe.dependencies:
                visit(dep)
            active.pop()
            seen.add(name)
            ordered.append(recipe)

        for name in names:
            visit(name)
        return ordered

    def reverse_dependencies(self, names):
        affected = set(names)
        while True:
            added = {r.name for r in self.recipes.values() if affected.intersection(r.dependencies)} - affected
            if not added:
                break
            affected |= added
        return [r for r in self.plan(sorted(affected)) if r.name in affected]
