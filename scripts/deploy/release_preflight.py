"""Read-only candidate inspection, never a live check or an atomic snapshot.

Only the listed inputs are hashed. Ignored files and external build dependencies
are not attested. No application imports, migration execution, Docker or database.
"""
from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

INPUTS = ("compose.yaml", "server/Dockerfile", "server/requirements.lock",
          "server/pyproject.toml", "server/alembic.ini", "server/migrations/env.py")
VERSIONS = "server/migrations/versions"


class Rejected(Exception):
    def __init__(self, code: str, exit_code: int = 1):
        self.code, self.exit_code = code, exit_code


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Rejected("invalid_arguments", 2)


def git(tree: Path, *args: str) -> bytes:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="")
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
             "-c", "core.hooksPath=" + os.devnull,
             "-c", "core.excludesFile=" + os.devnull,
             "-c", "core.attributesFile=" + os.devnull,
             "-c", "status.submoduleSummary=false", "-c", "protocol.allow=never",
             "-C", str(tree), *args],
            capture_output=True, env=env, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Rejected("git_unavailable", 2) from None
    if result.returncode:
        raise Rejected("git_failed", 2)
    return result.stdout


def snapshot(tree: Path) -> tuple[str, bytes]:
    head = git(tree, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    state = git(tree, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                "--ignore-submodules=none")
    return head, state


def safe_file(tree: Path, name: str) -> Path:
    current = tree
    for part in Path(name).parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise Rejected("linked_input")
    if not current.is_file():
        raise Rejected("missing_input")
    if current.stat().st_nlink != 1:
        raise Rejected("linked_input")
    return current


METADATA_KEYS = {"revision", "down_revision", "branch_labels", "depends_on"}


def literal_assignment(node):
    if isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    else:
        targets, value = [node.target], node.value
    if any(not isinstance(target, ast.Name) for target in targets):
        raise Rejected("unsupported_migration_metadata")
    return [target.id for target in targets], value


def metadata(content: bytes) -> tuple[str, tuple[str, ...]]:
    """Recognize this repository's static declarations, not Python execution semantics.

    Imports/functions are not evaluated. The sa.text literal SQL constants used by
    existing revisions are permitted; other executable module statements fail closed.
    Dependencies and function bodies remain trusted code outside this attestation.
    """
    try:
        module = ast.parse(content)
        values = {}
        for node in module.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if any(alias.name == "*" or (alias.asname or alias.name.split(".")[0]) in METADATA_KEYS
                       for alias in node.names):
                    raise Rejected("unsupported_migration_metadata")
                continue
            if isinstance(node, ast.FunctionDef):
                if node.name in METADATA_KEYS or node.decorator_list:
                    raise Rejected("unsupported_migration_metadata")
                for default in [*node.args.defaults, *node.args.kw_defaults]:
                    if default is not None:
                        ast.literal_eval(default)
                annotations = [node.returns, *(arg.annotation for arg in
                    [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs])]
                if node.args.vararg:
                    annotations.append(node.args.vararg.annotation)
                if node.args.kwarg:
                    annotations.append(node.args.kwarg.annotation)
                if any(isinstance(part, (ast.Call, ast.NamedExpr))
                       for annotation in annotations if annotation is not None
                       for part in ast.walk(annotation)):
                    raise Rejected("unsupported_migration_metadata")
                continue
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                raise Rejected("unsupported_migration_metadata")
            names, value = literal_assignment(node)
            if isinstance(node, ast.AnnAssign) and any(
                isinstance(part, (ast.Call, ast.NamedExpr)) for part in ast.walk(node.annotation)
            ):
                raise Rejected("unsupported_migration_metadata")
            selected = METADATA_KEYS.intersection(names)
            if selected:
                if selected.intersection(values):
                    raise Rejected("duplicate_metadata")
                result = ast.literal_eval(value)
                values.update((name, result) for name in selected)
            elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                  and isinstance(value.func.value, ast.Name) and value.func.value.id == "sa"
                  and value.func.attr == "text" and len(value.args) == 1 and not value.keywords
                  and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str)):
                continue
            else:
                ast.literal_eval(value)
        revision, parent = values["revision"], values["down_revision"]
        if values.get("branch_labels") is not None or values.get("depends_on") is not None:
            raise Rejected("unsupported_migration_metadata")
        parents = () if parent is None else ((parent,) if isinstance(parent, str) else parent)
        if not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9_]+", revision):
            raise Rejected("invalid_migration_metadata")
        if not isinstance(parents, (tuple, list)) or any(
            not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_]+", item)
            for item in parents
        ) or len(set(parents)) != len(parents):
            raise Rejected("invalid_migration_metadata")
        return revision, tuple(parents)
    except (SyntaxError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise Rejected("invalid_migration_metadata") from None


def check_git_configuration(tree: Path) -> None:
    """Read only standard Git metadata before Git can expand configuration includes.

    Supports ordinary repositories and standard linked worktrees. This is not a
    sandbox for hostile repositories or concurrent edits to Git administrative files.
    """
    marker = tree / ".git"
    if marker.is_symlink() or getattr(marker, "is_junction", lambda: False)():
        raise Rejected("unsupported_git_layout", 2)
    if marker.is_dir():
        common = admin = marker
    elif marker.is_file():
        text = safe_file(tree, ".git").read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir: ") or "\n" in text:
            raise Rejected("unsupported_git_layout", 2)
        admin = (tree / text[8:]).resolve(strict=True)
        if admin.parent.name != "worktrees" or admin.parent.parent.name != ".git":
            raise Rejected("unsupported_git_layout", 2)
        common = admin.parent.parent
        relative = safe_file(admin, "commondir").read_text(encoding="utf-8").strip()
        backlink = safe_file(admin, "gitdir").read_text(encoding="utf-8").strip()
        if (admin / relative).resolve() != common or Path(backlink).resolve() != marker:
            raise Rejected("unsupported_git_layout", 2)
    else:
        raise Rejected("not_repository_root", 2)
    config_files = [(common, "config")]
    for directory, filename in config_files:
        if not (directory / filename).exists():
            continue
        raw = safe_file(directory, filename).read_text(encoding="utf-8")
        # Reject syntax this deliberately small parser cannot faithfully interpret.
        if any(line.rstrip().endswith("\\") for line in raw.splitlines()):
            raise Rejected("unsupported_git_configuration", 2)
        parser = configparser.ConfigParser(interpolation=None, strict=True,
                                            delimiters=("=",), allow_no_value=True)
        try:
            # Git ignores indentation; ConfigParser otherwise treats deeper
            # section headers as continuation values. Continuations are refused
            # above, so normalizing indentation preserves the supported syntax.
            parser.read_string("\n".join(line.strip() for line in raw.splitlines()))
        except (configparser.Error, AttributeError):
            raise Rejected("unsupported_git_configuration", 2) from None
        if parser.defaults():
            raise Rejected("unsupported_git_configuration", 2)
        for section in parser.sections():
            base = re.split(r'[ ."]', section.lower(), maxsplit=1)[0]
            options = set(parser[section])
            if base == "filter":
                raise Rejected("unsafe_git_filters", 2)
            if base in {"include", "includeif"}:
                raise Rejected("unsafe_git_includes", 2)
            if (base == "extensions" and "partialclone" in options or
                    base == "remote" and options.intersection({"promisor", "partialclonefilter"})):
                raise Rejected("unsupported_partial_clone", 2)
            if base == "core" and options.intersection({"worktree", "excludesfile", "attributesfile"}):
                raise Rejected("unsafe_git_paths", 2)
            if base not in {"core", "extensions", "user", "remote", "branch", "credential"}:
                raise Rejected("unsupported_git_configuration", 2)
            if base == "extensions" and options - {"worktreeconfig", "objectformat"}:
                raise Rejected("unsupported_git_configuration", 2)
            if base == "extensions" and "worktreeconfig" in options:
                if filename != "config":
                    raise Rejected("unsupported_git_configuration", 2)
                flag = parser[section]["worktreeconfig"]
                if flag is None or flag.lower() in {"true", "yes", "on", "1"}:
                    config_files.append((admin, "config.worktree"))
                elif flag.lower() not in {"false", "no", "off", "0", ""}:
                    raise Rejected("unsupported_git_configuration", 2)


def check_alembic_configuration(content: bytes) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(content.decode("utf-8"))
        options = parser["alembic"]
        if (options.get("script_location") != "migrations" or
                "version_locations" in options or
                options.get("recursive_version_locations", "false").lower() != "false" or
                options.get("sourceless", "false").lower() != "false"):
            raise Rejected("unsupported_alembic_configuration")
    except (configparser.Error, KeyError, UnicodeError):
        raise Rejected("unsupported_alembic_configuration") from None


def graph_heads(graph: dict[str, tuple[str, ...]]) -> list[str]:
    parents = {parent for values in graph.values() for parent in values}
    if parents - graph.keys():
        raise Rejected("missing_migration_parent")
    remaining = dict(graph)
    visited = set()
    while remaining:
        ready = {key for key, deps in remaining.items() if set(deps) <= visited}
        if not ready:
            raise Rejected("migration_cycle")
        visited.update(ready)
        for key in ready:
            del remaining[key]
    heads = sorted(graph.keys() - parents)
    if len(heads) != 1:
        raise Rejected("migration_head_count")
    return heads


def is_migration_filename(name: str) -> bool:
    # Alembic source-only loader excludes editor locks and __init__ prefixes.
    return name.endswith(".py") and not name.startswith((".#", "__init__"))


def inspect(tree: Path, expected: str, report: dict) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected):
        raise Rejected("invalid_expected_commit", 2)
    tree = tree.resolve(strict=True)
    check_git_configuration(tree)
    top = Path(os.fsdecode(git(tree, "rev-parse", "--show-toplevel")).strip()).resolve()
    if tree != top:
        raise Rejected("not_repository_root", 2)
    if any(item.startswith(b"160000 ") for item in
           git(tree, "ls-files", "--stage", "-z").split(b"\0")):
        raise Rejected("unsupported_submodules", 2)
    before = snapshot(tree)
    report["observed_commit"] = before[0]
    if before[0] != expected.lower():
        raise Rejected("commit_mismatch")
    if before[1]:
        raise Rejected("dirty_tree")
    entries = git(tree, "ls-files", "-v", "-z").split(b"\0")
    if any(entry and (entry[:1].islower() or entry[:1] == b"S") for entry in entries):
        raise Rejected("hidden_index_changes")
    tracked = {os.fsdecode(entry[2:]) for entry in entries if entry}
    migrations = sorted(name for name in tracked if name.startswith(VERSIONS + "/")
                        and is_migration_filename(Path(name).name))
    if any("/" in name[len(VERSIONS) + 1:] for name in migrations):
        raise Rejected("unsupported_nested_migrations")
    if not migrations:
        raise Rejected("missing_migrations")
    directory = tree / VERSIONS
    for ancestor in (directory, *directory.parents):
        if ancestor == tree:
            break
        if ancestor.is_symlink() or getattr(ancestor, "is_junction", lambda: False)():
            raise Rejected("linked_input")
    disk_migrations = {VERSIONS + "/" + item.name for item in directory.iterdir()
                       if is_migration_filename(item.name)}
    if disk_migrations - set(migrations):
        raise Rejected("untracked_migration")
    hashes, graph = {}, {}
    for name in [*INPUTS, *migrations]:
        if name not in tracked:
            raise Rejected("untracked_input")
        content = safe_file(tree, name).read_bytes()
        hashes[name] = hashlib.sha256(content).hexdigest()
        if name == "server/alembic.ini":
            check_alembic_configuration(content)
        if name in migrations:
            revision, parents = metadata(content)
            if revision in graph:
                raise Rejected("duplicate_migration_revision")
            graph[revision] = parents
    heads = graph_heads(graph)
    if snapshot(tree) != before:
        raise Rejected("tree_changed_during_check")
    report.update(input_sha256=hashes, migration_heads=heads, status="candidate_consistent")


def main(argv=None) -> int:
    report = dict(schema_version=1, status="rejected", expected_commit=None,
                  observed_commit=None, migration_heads=[], input_sha256={}, errors=[],
                  live_status="not_checked")
    code = 0
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--tree", required=True)
        parser.add_argument("--expected-commit", required=True)
        args = parser.parse_args(argv)
        if re.fullmatch(r"[0-9a-fA-F]{40}", args.expected_commit):
            report["expected_commit"] = args.expected_commit.lower()
        inspect(Path(args.tree), args.expected_commit, report)
    except Rejected as error:
        code = error.exit_code
        report["errors"].append(error.code)
    except (OSError, UnicodeError, RuntimeError):
        code = 2
        report["errors"].append("input_unavailable")
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
