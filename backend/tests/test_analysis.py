"""Analysis tests: traceback parsing, route discovery, project analysis, ranking."""

from __future__ import annotations

from pathlib import Path

from app.analysis.api_analyzer import concretize_path, discover_routes, routes_from_openapi
from app.analysis.code_search import (
    extract_identifiers,
    extract_quoted_strings,
    extract_symbols,
    search_code,
)
from app.analysis.log_analyzer import clip_traceback, failures_from_pytest_output
from app.analysis.project_analyzer import analyze_project
from app.analysis.relevance_ranker import rank_files
from app.analysis.stacktrace_parser import (
    parse_counts,
    parse_short_summary,
    parse_traceback,
    split_pytest_failures,
)

CLASSIC = '''Traceback (most recent call last):
  File "/app/main.py", line 15, in get_user
    return user["username"]
           ~~~~^^^^^^^^^^^^
KeyError: 'username'
'''

PYTEST_BLOCK = """
    def test_get_user():
>       response = client.get("/users/1")

tests/test_users.py:21:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    @app.get("/users/{user_id}")
    def get_user(user_id: int):
>           "username": user["username"],
E       KeyError: 'username'

main.py:42: KeyError
"""

FULL_OUTPUT = f"""=================================== FAILURES ===================================
____________________________ test_get_user _____________________________
{PYTEST_BLOCK}
=========================== short test summary info ============================
FAILED tests/test_users.py::test_get_user - KeyError: 'username'
2 failed, 4 passed, 1 warning in 1.03s
"""


def test_parse_classic_traceback():
    parsed = parse_traceback(CLASSIC)
    assert parsed.error_type == "KeyError"
    assert parsed.message == "'username'"
    assert parsed.frames[-1].line == 15


def test_parse_pytest_block_finds_raising_line():
    parsed = parse_traceback(PYTEST_BLOCK)
    assert parsed.error_type == "KeyError"
    files = {(frame.file, frame.line) for frame in parsed.frames}
    assert ("main.py", 42) in files
    assert ("tests/test_users.py", 21) in files


def test_parse_absolute_windows_path():
    """pytest emits absolute paths when it cannot compute a relative one."""
    text = "C:\\Users\\dev\\proj\\main.py:42: KeyError"
    parsed = parse_traceback(text)
    assert parsed.frames, "an absolute Windows path must still be parsed as a frame"
    assert parsed.frames[0].line == 42
    assert parsed.frames[0].file.endswith("main.py")


def test_parse_counts_without_equals_decoration():
    """`pytest -q` prints the tally with no '=' padding."""
    counts = parse_counts("2 failed, 4 passed, 1 warning in 1.03s")
    assert counts["failed"] == 2
    assert counts["passed"] == 4


def test_parse_counts_with_equals_decoration():
    counts = parse_counts("======== 1 failed, 6 passed, 2 errors in 0.42s ========")
    assert counts == {
        "passed": 6, "failed": 1, "errors": 2, "skipped": 0, "xfailed": 0, "xpassed": 0
    }


def test_parse_counts_handles_no_tests():
    assert parse_counts("no tests ran in 0.01s")["passed"] == 0


def test_parse_short_summary():
    entries = parse_short_summary(FULL_OUTPUT)
    assert entries[0]["node_id"] == "tests/test_users.py::test_get_user"
    assert "KeyError" in entries[0]["detail"]


def test_split_pytest_failures():
    blocks = split_pytest_failures(FULL_OUTPUT)
    assert [name for name, _ in blocks] == ["test_get_user"]


def test_failures_from_pytest_output_prefers_app_frame(tmp_path: Path):
    (tmp_path / "main.py").write_text("x = 1\n" * 60, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_users.py").write_text("def test_get_user():\n    pass\n" * 15, encoding="utf-8")
    failures = failures_from_pytest_output(
        FULL_OUTPUT, "", project_root=tmp_path, short_summary=parse_short_summary(FULL_OUTPUT)
    )
    assert len(failures) == 1
    failure = failures[0]
    assert failure.error_type == "KeyError"
    # The app file is the culprit; the test file is only where it surfaced.
    assert failure.file == "main.py"
    assert failure.line == 42
    assert failure.test == "tests/test_users.py::test_get_user"


def test_clip_traceback_keeps_both_ends():
    text = "START" + ("x" * 40_000) + "END-KeyError"
    clipped = clip_traceback(text, limit=1000)
    assert clipped.startswith("START")
    assert clipped.endswith("END-KeyError")
    assert len(clipped) < 1400


# ---------------------------------------------------------------- routes ---
def test_discover_routes(sample_project: Path):
    routes, info = discover_routes(sample_project)
    signatures = {route.signature for route in routes}
    assert "GET /health" in signatures
    assert "GET /items/{item_id}" in signatures
    assert "main.py" in info["app_files"]


def test_discover_routes_with_router_prefix(workspace: Path):
    (workspace / "api.py").write_text(
        '''from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/v1")
app = FastAPI()


@router.post("/orders")
def create_order():
    return {}


@app.get("/ping")
def ping():
    return {}


app.include_router(router)
''',
        encoding="utf-8",
    )
    routes, _info = discover_routes(workspace)
    signatures = {route.signature for route in routes}
    assert "POST /v1/orders" in signatures
    assert "GET /ping" in signatures


def test_routes_from_openapi():
    schema = {
        "paths": {
            "/users/{user_id}": {
                "get": {
                    "operationId": "get_user",
                    "responses": {"200": {}, "404": {}},
                    "parameters": [{"name": "user_id"}],
                }
            }
        }
    }
    routes = routes_from_openapi(schema)
    assert routes[0].signature == "GET /users/{user_id}"
    assert routes[0].status_codes == [200, 404]


def test_concretize_path():
    assert concretize_path("/users/{user_id}") == "/users/1"
    assert concretize_path("/health") == "/health"


# -------------------------------------------------------------- analyzer ---
def test_analyze_project(sample_project: Path):
    metadata = analyze_project(sample_project)
    assert metadata.language == "python"
    assert metadata.framework == "fastapi"
    assert metadata.entry_point == "main.py"
    assert metadata.test_framework == "pytest"
    assert "tests/test_items.py" in metadata.test_files
    assert len(metadata.routes) == 2


def test_analyze_handles_syntax_error(workspace: Path):
    (workspace / "broken.py").write_text("def oops(:\n    pass\n", encoding="utf-8")
    metadata = analyze_project(workspace)
    assert "broken.py" in metadata.source_files


# ---------------------------------------------------------------- search ---
def test_search_code(sample_project: Path):
    matches = search_code(sample_project, "ITEMS")
    assert any(match.path == "main.py" for match in matches)


def test_extract_symbols():
    symbols = extract_symbols(
        "class A:\n    def b(self):\n        pass\n\n\ndef c():\n    pass\n", "x.py"
    )
    names = {(symbol.name, symbol.kind) for symbol in symbols}
    assert ("A", "class") in names
    assert ("b", "method") in names
    assert ("c", "function") in names


def test_extract_quoted_strings():
    assert extract_quoted_strings("KeyError: 'username'") == ["username"]


def test_extract_identifiers_skips_keywords():
    identifiers = extract_identifiers("return user_record and payload")
    assert "user_record" in identifiers
    assert "return" not in identifiers


# --------------------------------------------------------------- ranking ---
def test_rank_files_puts_stack_trace_file_first(sample_project: Path):
    metadata = analyze_project(sample_project)
    failures = failures_from_pytest_output(
        FULL_OUTPUT, "", project_root=sample_project,
        short_summary=parse_short_summary(FULL_OUTPUT),
    )
    ranked = rank_files(sample_project, failures[0], metadata)
    assert ranked
    assert ranked[0].path == "main.py"
    assert any("stack trace" in reason for reason in ranked[0].reasons)
