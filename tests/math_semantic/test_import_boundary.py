"""The extracted package must be independent of frozen evaluation infrastructure."""

from __future__ import annotations

import ast
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "deeptutor" / "math_semantic"
MAP_PATH = ROOT / "evaluation" / "math_semantic_extraction" / "source_map.json"
FORBIDDEN = {"tutor_demo", "evaluation", "tests", "scripts"}
EXPECTED_COUNTS = {
    "MIGRATE": 4,
    "MIGRATE_WITH_ADAPTATION": 17,
    "REGRESSION_ONLY": 36,
    "DO_NOT_MIGRATE": 22,
    "DELETE_AFTER_CUTOVER": 24,
    "REQUIRES_OWNER_DECISION": 4,
}


def _module(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: Path) -> set[str]:
    """Walk all scopes, including lazy, relative and TYPE_CHECKING imports."""
    package = _module(path)
    if path.name != "__init__.py":
        package = package.rpartition(".")[0]
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = "." * node.level + (node.module or "")
            resolved = importlib.util.resolve_name(name, package) if node.level else name
            imports.add(resolved)
            if node.module is None:
                imports.update(resolved + "." + alias.name for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            imports.add(node.args[0].value)
    return imports


def _local_path(module: str) -> Path | None:
    candidate = ROOT.joinpath(*module.split("."))
    for path in (candidate.with_suffix(".py"), candidate / "__init__.py"):
        if path.is_file():
            return path
    return None


def _package_paths(module: str) -> set[Path]:
    parts = module.split(".")
    return {
        candidate
        for index in range(1, len(parts) + 1)
        if (candidate := ROOT.joinpath(*parts[:index], "__init__.py")).is_file()
    }


def test_whitelist_accounting_and_native_source_map():
    mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    assert mapping["provenance"] == {
        "deeptutor_base_sha": "73774dc26a734c040d3f91bc887060127475178f",
        "tutor_demo_planning_sha": "a2a1905dc41eed3e5a574304993c2747dcb0838c",
        "frozen_math_runtime_oracle_sha": "76d5d9697186d086fb967e79a9e08e394b0d5474",
        "whitelist_version": "MATH-ENGINE-EXTRACTION-WHITELIST-01",
    }
    rows = mapping["rows"]
    assert len(rows) == len({row["path"] for row in rows}) == 107
    assert Counter(row["classification"] for row in rows) == EXPECTED_COUNTS
    mapped: set[str] = set()
    for row in rows:
        assert row["reason"] and row["disposition"] and row["excluded_responsibility"]
        if row["classification"] in {"MIGRATE", "MIGRATE_WITH_ADAPTATION"}:
            assert row["production_slices"] and row["oracle_coverage"]
            assert row["frozen_source_sha256"] == row["planning_source_sha256"]
            assert len(row["frozen_source_sha256"]) == 64
            for target in row["new_owners"]:
                assert (ROOT / target).is_file(), target
            mapped.update(row["new_owners"])
        else:
            assert not row["production_slices"]
            assert not row["new_owners"]
    mapped.update(item["path"] for item in mapping["native_boundary_additions"])
    assert {path.relative_to(ROOT).as_posix() for path in PACKAGE.glob("*.py")} <= mapped


def test_all_native_import_scopes_have_only_approved_dependencies():
    for path in PACKAGE.glob("*.py"):
        imports = _imports(path)
        for name in imports:
            assert name.split(".")[0] not in FORBIDDEN, (path, name)
            assert (
                name.split(".")[0] in sys.stdlib_module_names
                or name == "__future__"
                or name.startswith("sympy")
                or name.startswith("deeptutor.math_semantic")
            ), (path, name)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "__import__":
                    assert (
                        node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "sympy"
                    ), "only the fixed optional verifier availability probe is allowed"
                assert not (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "importlib"
                    and node.func.attr == "import_module"
                )
            if isinstance(node, ast.Attribute):
                assert not (
                    isinstance(node.value, ast.Name)
                    and node.value.id == "sys"
                    and node.attr == "path"
                )
        assert "sqlite3" not in imports, "storage drivers belong to host composition"


def test_transitive_import_closure_does_not_reach_old_or_regression_packages():
    pending = list(PACKAGE.glob("*.py"))
    adapter = ROOT / "deeptutor/services/session/math_semantic_persistence.py"
    assert adapter.is_file()
    pending.append(adapter)
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        for name in _imports(path):
            assert name.split(".")[0] not in FORBIDDEN, (path, name)
            pending.extend(_package_paths(name) - visited)
            local = _local_path(name)
            if local is not None and local not in visited:
                pending.append(local)
    assert PACKAGE / "accepted.py" in visited
    assert adapter in visited
    assert ROOT / "deeptutor/core/context.py" in visited


def test_package_imports_with_frozen_engine_and_fixture_imports_blocked():
    script = """
import importlib, importlib.abc, pathlib, pkgutil, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
class DenyOracle(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'tutor_demo', 'tests', 'evaluation', 'scripts'}:
            raise AssertionError('production imported oracle: ' + fullname)
sys.meta_path.insert(0, DenyOracle())
package = importlib.import_module('deeptutor.math_semantic')
for info in pkgutil.walk_packages(package.__path__, prefix=package.__name__ + '.'):
    module = importlib.import_module(info.name)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
assert not any(name.startswith('tutor_demo') for name in sys.modules)
print('independent-native-import: PASS')
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(ROOT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "independent-native-import: PASS"
