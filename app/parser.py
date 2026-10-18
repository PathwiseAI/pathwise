"""Static Python source analyzer using the ast module.

Discovers files, functions, and call relationships without executing any code.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories always excluded from indexing
EXCLUDED_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "env", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".eggs",
    "dist", "build", ".egg-info", "site-packages",
}

MAX_AST_DEPTH = 50


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ParsedFunction:
    """A function discovered by static analysis."""
    function_id: str
    name: str
    qualified_name: str
    file_path: str          # relative path within the repo
    start_line: int
    end_line: int
    is_method: bool = False
    is_async: bool = False


@dataclass
class ParsedCall:
    """A resolved function call."""
    caller_id: str
    callee_id: str
    call_line: int


@dataclass
class UnresolvedCallRecord:
    """A call that could not be resolved to a known function."""
    caller_id: str
    call_text: str
    call_line: int


@dataclass
class ParsedFile:
    """A discovered Python file."""
    file_path: str          # relative path
    absolute_path: str


@dataclass
class ParseResult:
    """Aggregate result of parsing a repository."""
    repository_id: str
    root_path: str
    files: list[ParsedFile] = field(default_factory=list)
    functions: list[ParsedFunction] = field(default_factory=list)
    calls: list[ParsedCall] = field(default_factory=list)
    unresolved_calls: list[UnresolvedCallRecord] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_repo_id(repo_path: str) -> str:
    """Create a stable, short repository identifier from its absolute path."""
    norm = os.path.normpath(os.path.abspath(repo_path)).replace("\\", "/").lower()
    return hashlib.sha256(norm.encode()).hexdigest()[:12]


def make_function_id(repo_id: str, rel_path: str, qualified_name: str) -> str:
    """Create a stable function identifier: repo_id::rel_path::qualified_name."""
    return f"{repo_id}::{rel_path}::{qualified_name}"


def _get_call_text(node: ast.Call) -> str | None:
    """Extract a human-readable call target from an ast.Call node."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = []
        current = func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)
    return None


# ── AST Visitor ────────────────────────────────────────────────────────────────

class _FunctionVisitor(ast.NodeVisitor):
    """Walk an AST to collect function definitions and their call expressions."""

    def __init__(self, repo_id: str, rel_path: str):
        self.repo_id = repo_id
        self.rel_path = rel_path
        self.functions: list[ParsedFunction] = []
        self.raw_calls: list[tuple[str, str, int]] = []  # (caller_qname, call_text, line)
        self._scope_stack: list[str] = []
        self._depth = 0

    def _current_qualified_name(self, name: str) -> str:
        if self._scope_stack:
            return ".".join(self._scope_stack) + "." + name
        return name

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Process a function/method definition."""
        self._depth += 1
        if self._depth > MAX_AST_DEPTH:
            self._depth -= 1
            return

        qname = self._current_qualified_name(node.name)
        fid = make_function_id(self.repo_id, self.rel_path, qname)

        is_method = len(self._scope_stack) > 0 and any(
            isinstance(f, ParsedFunction) and not f.is_method
            for f in []  # heuristic: parent is a class
        )
        # Better heuristic: check if parent scope name starts with uppercase
        is_method = (
            len(self._scope_stack) > 0
            and self._scope_stack[-1][:1].isupper()
        )

        self.functions.append(ParsedFunction(
            function_id=fid,
            name=node.name,
            qualified_name=qname,
            file_path=self.rel_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            is_method=is_method,
            is_async=isinstance(node, ast.AsyncFunctionDef),
        ))

        # Collect call expressions within this function body
        self._scope_stack.append(node.name)
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and child is not node:
                call_text = _get_call_text(child)
                if call_text:
                    self.raw_calls.append((qname, call_text, child.lineno))
        # Visit nested definitions
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._visit_function(child)
            elif isinstance(child, ast.ClassDef):
                self._visit_class(child)
        self._scope_stack.pop()
        self._depth -= 1

    def _visit_class(self, node: ast.ClassDef) -> None:
        """Process a class definition to find methods."""
        self._depth += 1
        if self._depth > MAX_AST_DEPTH:
            self._depth -= 1
            return

        self._scope_stack.append(node.name)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._visit_function(child)
            elif isinstance(child, ast.ClassDef):
                self._visit_class(child)
        self._scope_stack.pop()
        self._depth -= 1

    def visit_Module(self, node: ast.Module) -> None:
        """Visit top-level module definitions."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._visit_function(child)
            elif isinstance(child, ast.ClassDef):
                self._visit_class(child)


# ── Call Resolution ────────────────────────────────────────────────────────────

def _resolve_calls(
    repo_id: str,
    rel_path: str,
    functions: list[ParsedFunction],
    raw_calls: list[tuple[str, str, int]],
    all_functions: dict[str, ParsedFunction],
    import_map: dict[str, str],
) -> tuple[list[ParsedCall], list[UnresolvedCallRecord]]:
    """Resolve raw call texts to known function IDs.

    Strategies (in order):
    1. Same-file qualified name match.
    2. Import-resolved match.
    3. Bare name match across the repo (only if unique).
    """
    resolved: list[ParsedCall] = []
    unresolved: list[UnresolvedCallRecord] = []

    local_funcs = {f.qualified_name: f for f in functions}

    for caller_qname, call_text, call_line in raw_calls:
        caller_id = make_function_id(repo_id, rel_path, caller_qname)
        callee_func: ParsedFunction | None = None

        # 1. Same-file: direct name or attribute match
        if call_text in local_funcs:
            callee_func = local_funcs[call_text]
        else:
            # Try stripping 'self.' prefix for method calls
            stripped = call_text.removeprefix("self.")
            if stripped != call_text and stripped in local_funcs:
                callee_func = local_funcs[stripped]

        # 2. Import-resolved
        if callee_func is None and call_text in import_map:
            target_qname = import_map[call_text]
            if target_qname in all_functions:
                callee_func = all_functions[target_qname]

        # 3. Bare name across repo (only if unique)
        if callee_func is None:
            bare = call_text.split(".")[-1]
            candidates = [f for key, f in all_functions.items() if f.name == bare]
            if len(candidates) == 1:
                callee_func = candidates[0]

        if callee_func is not None and callee_func.function_id != caller_id:
            resolved.append(ParsedCall(
                caller_id=caller_id,
                callee_id=callee_func.function_id,
                call_line=call_line,
            ))
        else:
            # Skip built-in-looking calls
            if call_text and not call_text[0].isupper() and call_text not in {
                "print", "len", "range", "int", "str", "float", "list", "dict",
                "set", "tuple", "bool", "type", "isinstance", "hasattr", "getattr",
                "setattr", "super", "enumerate", "zip", "map", "filter", "sorted",
                "reversed", "any", "all", "min", "max", "sum", "abs", "round",
                "open", "input", "format", "repr", "hash", "id", "vars", "dir",
                "callable", "iter", "next", "property", "staticmethod", "classmethod",
            }:
                unresolved.append(UnresolvedCallRecord(
                    caller_id=caller_id,
                    call_text=call_text,
                    call_line=call_line,
                ))

    return resolved, unresolved


# ── Import Extraction ──────────────────────────────────────────────────────────

def _extract_imports(tree: ast.Module, repo_root: Path, file_path: Path) -> dict[str, str]:
    """Extract import mappings: local_name -> qualified_function_name within the repo.

    Only resolves imports that appear to be from within the same repository.
    """
    import_map: dict[str, str] = {}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # Convert module path to file path to see if it's in the repo
            module_parts = node.module.split(".")
            candidate = repo_root / Path(*module_parts)
            candidate_file = candidate.with_suffix(".py")
            candidate_init = candidate / "__init__.py"

            is_repo_module = candidate_file.exists() or candidate_init.exists()

            if is_repo_module and node.names:
                # Determine the relative path of the target module
                if candidate_file.exists():
                    target_rel = candidate_file.relative_to(repo_root).as_posix()
                else:
                    target_rel = (candidate / "__init__.py").relative_to(repo_root).as_posix()

                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local_name = alias.asname or alias.name
                    # The imported name is a function in the target file
                    import_map[local_name] = f"{target_rel}::{alias.name}"

    return import_map


# ── Main Parse Function ───────────────────────────────────────────────────────

def parse_repository(
    repo_path: str,
    *,
    max_file_size_kb: int = 500,
    max_file_count: int = 1000,
) -> ParseResult:
    """Parse a Python repository and extract files, functions, and calls.

    Args:
        repo_path: Absolute or relative path to the repository root.
        max_file_size_kb: Maximum file size in KB to parse.
        max_file_count: Maximum number of files to process.

    Returns:
        ParseResult with all discovered entities and diagnostics.
    """
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Repository path does not exist: {root}")

    repo_id = make_repo_id(str(root))
    result = ParseResult(repository_id=repo_id, root_path=str(root))

    # Phase 1: Discover files
    py_files: list[tuple[str, Path]] = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Filter excluded directories in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDED_DIRS and not d.startswith(".")
        ]
        # Check for symlink escape
        real_dir = Path(dirpath).resolve()
        if not str(real_dir).startswith(str(root)):
            result.warnings.append(f"Skipped symlink escaping repo root: {dirpath}")
            dirnames.clear()
            continue

        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            file_count += 1
            if file_count > max_file_count:
                result.warnings.append(
                    f"File count limit reached ({max_file_count}). Some files not indexed."
                )
                break

            fpath = Path(dirpath) / fname
            rel = fpath.relative_to(root).as_posix()

            # Size check
            try:
                size_kb = fpath.stat().st_size / 1024
            except OSError:
                result.skipped_files.append(rel)
                continue

            if size_kb > max_file_size_kb:
                result.skipped_files.append(rel)
                result.warnings.append(f"Skipped large file ({size_kb:.0f}KB): {rel}")
                continue

            py_files.append((rel, fpath))
            result.files.append(ParsedFile(file_path=rel, absolute_path=str(fpath)))

        if file_count > max_file_count:
            break

    # Phase 2: Parse each file, collect functions and raw calls
    file_visitors: list[tuple[str, _FunctionVisitor, dict[str, str]]] = []

    for rel_path, abs_path in py_files:
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError as e:
            result.parse_errors.append(f"Syntax error in {rel_path}: {e}")
            continue
        except Exception as e:
            result.parse_errors.append(f"Failed to read {rel_path}: {e}")
            continue

        visitor = _FunctionVisitor(repo_id, rel_path)
        visitor.visit_Module(tree)
        result.functions.extend(visitor.functions)

        import_map = _extract_imports(tree, root, abs_path)
        file_visitors.append((rel_path, visitor, import_map))

    # Phase 3: Resolve calls across all files
    # Build a global qualified-name lookup: "rel_path::qname" -> ParsedFunction
    all_functions: dict[str, ParsedFunction] = {}
    for func in result.functions:
        key = f"{func.file_path}::{func.qualified_name}"
        all_functions[key] = func

    for rel_path, visitor, import_map in file_visitors:
        # Translate import_map values to ParsedFunction instances
        resolved_import_map: dict[str, str] = {}
        for local_name, target_key in import_map.items():
            if target_key in all_functions:
                resolved_import_map[local_name] = target_key

        local_funcs = [f for f in result.functions if f.file_path == rel_path]
        calls, unresolved = _resolve_calls(
            repo_id, rel_path, local_funcs, visitor.raw_calls,
            all_functions, resolved_import_map,
        )
        result.calls.extend(calls)
        result.unresolved_calls.extend(unresolved)

    logger.info(
        "Parsed %s: %d files, %d functions, %d calls resolved, %d unresolved",
        repo_id, len(result.files), len(result.functions),
        len(result.calls), len(result.unresolved_calls),
    )

    return result
