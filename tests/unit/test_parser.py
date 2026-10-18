"""Unit tests for the Python AST parser."""

import os
import tempfile
import textwrap

import pytest

from app.parser import (
    ParseResult,
    make_function_id,
    make_repo_id,
    parse_repository,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_repo_path():
    """Return the path to the sample_repo fixture."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "sample_repo")


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary repo with a simple Python file."""
    py_file = tmp_path / "module.py"
    py_file.write_text(textwrap.dedent("""
        def greet(name):
            return format_greeting(name)

        def format_greeting(name):
            return f"Hello, {name}!"
    """))
    return tmp_path


@pytest.fixture
def tmp_repo_with_classes(tmp_path):
    """Create a temp repo with class methods."""
    py_file = tmp_path / "models.py"
    py_file.write_text(textwrap.dedent("""
        class User:
            def __init__(self, name):
                self.name = name

            def greet(self):
                return format_name(self.name)

        def format_name(name):
            return name.strip().title()
    """))
    return tmp_path


@pytest.fixture
def tmp_repo_with_imports(tmp_path):
    """Create a temp repo with cross-file imports."""
    (tmp_path / "helpers.py").write_text(textwrap.dedent("""
        def helper_func():
            return 42
    """))
    (tmp_path / "main.py").write_text(textwrap.dedent("""
        from helpers import helper_func

        def entry():
            return helper_func()
    """))
    return tmp_path


@pytest.fixture
def tmp_repo_syntax_error(tmp_path):
    """Create a temp repo with a syntax error file."""
    (tmp_path / "good.py").write_text("def good(): pass\n")
    (tmp_path / "bad.py").write_text("def bad( \n")  # syntax error
    return tmp_path


@pytest.fixture
def tmp_repo_async(tmp_path):
    """Create a temp repo with async functions."""
    (tmp_path / "async_mod.py").write_text(textwrap.dedent("""
        async def fetch_data():
            return await process()

        async def process():
            return 1
    """))
    return tmp_path


@pytest.fixture
def tmp_repo_nested(tmp_path):
    """Create a temp repo with nested functions."""
    (tmp_path / "nested.py").write_text(textwrap.dedent("""
        def outer():
            def inner():
                return 1
            return inner()
    """))
    return tmp_path


# ── ID generation tests ────────────────────────────────────────────────────────

def test_make_repo_id_deterministic():
    """Same path should always produce the same ID."""
    id1 = make_repo_id("/some/path")
    id2 = make_repo_id("/some/path")
    assert id1 == id2
    assert len(id1) == 12


def test_make_repo_id_different_paths():
    """Different paths produce different IDs."""
    id1 = make_repo_id("/path/a")
    id2 = make_repo_id("/path/b")
    assert id1 != id2


def test_make_function_id_format():
    """Function ID follows the repo_id::path::qname format."""
    fid = make_function_id("abc123", "module.py", "my_func")
    assert fid == "abc123::module.py::my_func"


def test_make_function_id_prevents_collision():
    """Same name in different files produces different IDs."""
    id1 = make_function_id("repo", "a.py", "func")
    id2 = make_function_id("repo", "b.py", "func")
    assert id1 != id2


# ── Parser tests ───────────────────────────────────────────────────────────────

def test_parse_sample_repo(sample_repo_path):
    """Parse the sample_repo and check basic counts."""
    result = parse_repository(sample_repo_path)
    assert isinstance(result, ParseResult)
    assert len(result.files) >= 5  # api, service, calculator, persistence, utils
    assert len(result.functions) >= 10
    assert len(result.calls) >= 5
    assert result.repository_id


def test_parse_discovers_functions(tmp_repo):
    """Parser discovers top-level functions."""
    result = parse_repository(str(tmp_repo))
    names = [f.name for f in result.functions]
    assert "greet" in names
    assert "format_greeting" in names


def test_parse_resolves_direct_call(tmp_repo):
    """Parser resolves a direct function call within the same file."""
    result = parse_repository(str(tmp_repo))
    assert len(result.calls) >= 1
    caller_ids = [c.caller_id for c in result.calls]
    callee_ids = [c.callee_id for c in result.calls]
    # greet calls format_greeting
    greet = next(f for f in result.functions if f.name == "greet")
    fmt = next(f for f in result.functions if f.name == "format_greeting")
    assert greet.function_id in caller_ids
    assert fmt.function_id in callee_ids


def test_parse_class_methods(tmp_repo_with_classes):
    """Parser discovers class methods with qualified names."""
    result = parse_repository(str(tmp_repo_with_classes))
    qnames = [f.qualified_name for f in result.functions]
    assert "User.__init__" in qnames
    assert "User.greet" in qnames
    assert "format_name" in qnames


def test_parse_cross_file_imports(tmp_repo_with_imports):
    """Parser resolves cross-file imports."""
    result = parse_repository(str(tmp_repo_with_imports))
    assert len(result.calls) >= 1
    # entry() calls helper_func()
    entry = next(f for f in result.functions if f.name == "entry")
    helper = next(f for f in result.functions if f.name == "helper_func")
    call_pairs = [(c.caller_id, c.callee_id) for c in result.calls]
    assert (entry.function_id, helper.function_id) in call_pairs


def test_parse_handles_syntax_error(tmp_repo_syntax_error):
    """Parser handles syntax errors without aborting."""
    result = parse_repository(str(tmp_repo_syntax_error))
    assert len(result.parse_errors) >= 1
    # Good file should still be parsed
    names = [f.name for f in result.functions]
    assert "good" in names


def test_parse_async_functions(tmp_repo_async):
    """Parser discovers async functions."""
    result = parse_repository(str(tmp_repo_async))
    async_funcs = [f for f in result.functions if f.is_async]
    assert len(async_funcs) >= 2


def test_parse_nested_functions(tmp_repo_nested):
    """Parser discovers nested functions."""
    result = parse_repository(str(tmp_repo_nested))
    qnames = [f.qualified_name for f in result.functions]
    assert "outer" in qnames
    assert "outer.inner" in qnames


def test_parse_empty_repo(tmp_path):
    """Parser handles empty repository gracefully."""
    result = parse_repository(str(tmp_path))
    assert len(result.files) == 0
    assert len(result.functions) == 0
    assert len(result.calls) == 0


def test_parse_nonexistent_path():
    """Parser raises FileNotFoundError for nonexistent path."""
    with pytest.raises(FileNotFoundError):
        parse_repository("/nonexistent/path/that/does/not/exist")


def test_parse_file_size_limit(tmp_path):
    """Parser skips files exceeding the size limit."""
    big_file = tmp_path / "big.py"
    big_file.write_text("x = 1\n" * 100000)  # ~600KB
    result = parse_repository(str(tmp_path), max_file_size_kb=1)
    assert len(result.skipped_files) >= 1


def test_parse_duplicate_function_names(tmp_path):
    """Functions with same name in different files get unique IDs."""
    (tmp_path / "a.py").write_text("def process(): pass\n")
    (tmp_path / "b.py").write_text("def process(): pass\n")
    result = parse_repository(str(tmp_path))
    ids = [f.function_id for f in result.functions if f.name == "process"]
    assert len(ids) == 2
    assert ids[0] != ids[1]


def test_parse_records_line_numbers(tmp_repo):
    """Parser records start and end line numbers."""
    result = parse_repository(str(tmp_repo))
    for f in result.functions:
        assert f.start_line > 0
        assert f.end_line >= f.start_line


def test_parse_call_line_numbers(tmp_repo):
    """Parser records call-site line numbers."""
    result = parse_repository(str(tmp_repo))
    for c in result.calls:
        assert c.call_line > 0
