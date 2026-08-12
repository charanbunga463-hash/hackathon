"""Source-code search and symbol extraction.

Everything the agent learns about the code goes through here. There is no
`grep` subprocess: search is done in-process over the workspace so it stays
inside the path-security boundary.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..utils.filesystem import iter_files, read_text, relative_posix

SEARCHABLE_SUFFIXES = {
    ".py", ".pyi", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".cfg",
    ".ini", ".sql", ".js", ".ts", ".env",
}
MAX_MATCHES = 80
CONTEXT_LINES = 2


@dataclass
class SearchMatch:
    path: str
    line: int
    text: str
    context: str = ""
    score: float = 0.0

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "text": self.text[:400],
            "context": self.context[:1200],
            "score": round(self.score, 3),
        }


@dataclass
class SymbolInfo:
    name: str
    kind: str            # function | class | method | assignment
    path: str
    line: int
    end_line: int
    signature: str = ""
    parent: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "end_line": self.end_line,
            "signature": self.signature,
            "parent": self.parent,
        }


@dataclass
class CodeIndex:
    root: Path
    files: list[str] = field(default_factory=list)
    symbols: list[SymbolInfo] = field(default_factory=list)

    def symbols_named(self, name: str) -> list[SymbolInfo]:
        lowered = name.lower()
        return [s for s in self.symbols if s.name.lower() == lowered]

    def symbols_in(self, path: str) -> list[SymbolInfo]:
        return [s for s in self.symbols if s.path == path]


def searchable_files(root: Path) -> list[Path]:
    return [
        path
        for path in iter_files(root)
        if path.suffix.lower() in SEARCHABLE_SUFFIXES and path.is_file()
    ]


def build_index(root: Path) -> CodeIndex:
    index = CodeIndex(root=root)
    for path in searchable_files(root):
        relative = relative_posix(path, root)
        index.files.append(relative)
        if path.suffix == ".py":
            index.symbols.extend(extract_symbols(read_text(path), relative))
    return index


def extract_symbols(source: str, relative_path: str) -> list[SymbolInfo]:
    """AST-based symbol extraction; falls back to regex on syntax errors.

    A project with a SyntaxError is exactly the kind we need to repair, so the
    regex fallback matters — it is not dead code.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _regex_symbols(source, relative_path)

    symbols: list[SymbolInfo] = []

    def visit(node: ast.AST, parent: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    SymbolInfo(
                        name=child.name,
                        kind="method" if parent else "function",
                        path=relative_path,
                        line=child.lineno,
                        end_line=getattr(child, "end_lineno", child.lineno) or child.lineno,
                        signature=_signature(child),
                        parent=parent,
                    )
                )
                visit(child, child.name)
            elif isinstance(child, ast.ClassDef):
                symbols.append(
                    SymbolInfo(
                        name=child.name,
                        kind="class",
                        path=relative_path,
                        line=child.lineno,
                        end_line=getattr(child, "end_lineno", child.lineno) or child.lineno,
                        signature=f"class {child.name}",
                        parent=parent,
                    )
                )
                visit(child, child.name)
            elif isinstance(child, ast.Assign) and parent is None:
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        symbols.append(
                            SymbolInfo(
                                name=target.id,
                                kind="assignment",
                                path=relative_path,
                                line=child.lineno,
                                end_line=getattr(child, "end_lineno", child.lineno) or child.lineno,
                                signature=target.id,
                                parent=None,
                            )
                        )

    visit(tree, None)
    return symbols


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in node.args.args]
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)})"


_DEF_RE = re.compile(r"^\s*(async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")


def _regex_symbols(source: str, relative_path: str) -> list[SymbolInfo]:
    symbols: list[SymbolInfo] = []
    for number, line in enumerate(source.splitlines(), start=1):
        match = _DEF_RE.match(line)
        if match:
            keyword, name = match.group(1), match.group(2)
            symbols.append(
                SymbolInfo(
                    name=name,
                    kind="class" if keyword == "class" else "function",
                    path=relative_path,
                    line=number,
                    end_line=number,
                    signature=line.strip(),
                )
            )
    return symbols


def search_code(
    root: Path,
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    path_glob: str | None = None,
    limit: int = MAX_MATCHES,
) -> list[SearchMatch]:
    """Literal or regex search across the workspace with surrounding context."""
    if not query or not query.strip():
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except re.error:
        pattern = re.compile(re.escape(query), flags)

    matches: list[SearchMatch] = []
    for path in searchable_files(root):
        relative = relative_posix(path, root)
        if path_glob and not Path(relative).match(path_glob):
            continue
        content = read_text(path)
        if not content or not pattern.search(content):
            continue
        lines = content.splitlines()
        for number, line in enumerate(lines, start=1):
            if not pattern.search(line):
                continue
            start = max(0, number - 1 - CONTEXT_LINES)
            end = min(len(lines), number + CONTEXT_LINES)
            context = "\n".join(
                f"{i + 1:>4} | {lines[i]}" for i in range(start, end)
            )
            matches.append(
                SearchMatch(
                    path=relative,
                    line=number,
                    text=line.strip(),
                    context=context,
                    score=_match_score(relative, line, query),
                )
            )
            if len(matches) >= limit:
                matches.sort(key=lambda m: -m.score)
                return matches
    matches.sort(key=lambda m: -m.score)
    return matches


def _match_score(path: str, line: str, query: str) -> float:
    score = 1.0
    lowered_path = path.lower()
    if lowered_path.endswith(".py"):
        score += 0.6
    if "test" in lowered_path:
        score -= 0.2
    stripped = line.strip()
    if stripped.startswith(("def ", "async def ", "class ")):
        score += 0.8
    if stripped.startswith("#"):
        score -= 0.5
    if query and query.lower() in stripped.lower():
        score += 0.3
    return score


def find_symbol_definitions(root: Path, name: str) -> list[SymbolInfo]:
    hits: list[SymbolInfo] = []
    for path in searchable_files(root):
        if path.suffix != ".py":
            continue
        relative = relative_posix(path, root)
        for symbol in extract_symbols(read_text(path), relative):
            if symbol.name == name:
                hits.append(symbol)
    return hits


def enclosing_symbol(root: Path, relative_path: str, line: int) -> SymbolInfo | None:
    """Which function/class contains this line?"""
    target = root / relative_path
    if not target.exists():
        return None
    candidates = [
        symbol
        for symbol in extract_symbols(read_text(target), relative_path)
        if symbol.kind in {"function", "method", "class"}
        and symbol.line <= line <= max(symbol.end_line, symbol.line)
    ]
    if not candidates:
        return None
    # Innermost wins.
    return min(candidates, key=lambda s: s.end_line - s.line)


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
KEYWORDS = {
    "def", "class", "return", "import", "from", "if", "else", "elif", "for",
    "while", "try", "except", "finally", "with", "as", "in", "is", "not", "and",
    "or", "None", "True", "False", "self", "async", "await", "raise", "pass",
    "lambda", "yield", "assert", "global", "nonlocal", "del", "print", "str",
    "int", "dict", "list", "set", "float", "bool", "len", "range",
}


def extract_identifiers(text: str) -> list[str]:
    """Pull candidate symbols out of an error message or code snippet."""
    seen: dict[str, int] = {}
    for match in IDENTIFIER.finditer(text or ""):
        token = match.group(0)
        if token in KEYWORDS or len(token) < 3:
            continue
        seen[token] = seen.get(token, 0) + 1
    return [token for token, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


QUOTED = re.compile(r"['\"]([^'\"]{1,80})['\"]")


def extract_quoted_strings(text: str) -> list[str]:
    """`KeyError: 'username'` -> ['username'] — the highest-signal token there is."""
    return [m.group(1) for m in QUOTED.finditer(text or "") if m.group(1).strip()]
