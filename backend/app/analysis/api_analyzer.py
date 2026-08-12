"""FastAPI / Flask route discovery.

Static discovery is AST-based, not regex-based, so decorator arguments, routers
with prefixes and `include_router(...)` composition are handled correctly. The
uploaded module is *parsed*, never imported — discovery must not execute
untrusted code.

Runtime discovery (reading `/openapi.json` from a sandboxed instance) is layered
on top by `execution/` and merged here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..models.project import RouteInfo
from ..utils.filesystem import iter_files, read_text, relative_posix

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
FASTAPI_APP_CLASSES = {"FastAPI"}
ROUTER_CLASSES = {"APIRouter"}


class _RouteVisitor(ast.NodeVisitor):
    """Collect app/router objects, their prefixes, and decorated endpoints."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.app_names: set[str] = set()
        self.router_names: set[str] = set()
        self.router_prefixes: dict[str, str] = {}
        self.included: list[tuple[str, str]] = []   # (router_name, prefix)
        self.routes: list[RouteInfo] = []
        self.mount_prefixes: dict[str, str] = {}

    # -- object construction ------------------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            callee = _callee_name(node.value.func)
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if callee in FASTAPI_APP_CLASSES:
                    self.app_names.add(target.id)
                elif callee in ROUTER_CLASSES:
                    self.router_names.add(target.id)
                    prefix = _keyword_str(node.value, "prefix") or ""
                    self.router_prefixes[target.id] = prefix
        self.generic_visit(node)

    # -- include_router / mount --------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "include_router":
            router = None
            if node.args and isinstance(node.args[0], ast.Name):
                router = node.args[0].id
            elif node.args and isinstance(node.args[0], ast.Attribute):
                router = node.args[0].attr
            prefix = _keyword_str(node, "prefix") or ""
            if router:
                self.included.append((router, prefix))
        self.generic_visit(node)

    # -- decorated endpoints ------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)
        self.generic_visit(node)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            attr = decorator.func
            if not isinstance(attr, ast.Attribute):
                continue
            method = attr.attr.lower()
            owner = _callee_name(attr.value)
            if method == "route":
                # Flask style: @app.route("/x", methods=["POST"])
                methods = _keyword_list(decorator, "methods") or ["GET"]
                path = _first_string_arg(decorator) or ""
                for verb in methods:
                    self.routes.append(self._build(verb, path, owner, node, decorator))
                continue
            if method not in HTTP_METHODS:
                continue
            path = _first_string_arg(decorator)
            if path is None:
                continue
            self.routes.append(self._build(method, path, owner, node, decorator))

    def _build(
        self,
        method: str,
        path: str,
        owner: str | None,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        decorator: ast.Call,
    ) -> RouteInfo:
        status_code = _keyword_int(decorator, "status_code")
        response_model = _keyword_name(decorator, "response_model")
        parameters = [arg.arg for arg in node.args.args if arg.arg not in {"self", "cls"}]
        body_param = None
        for arg in node.args.args:
            annotation = _annotation_name(arg.annotation)
            if annotation and annotation not in {"int", "str", "float", "bool", "Request", "Response"}:
                if arg.arg not in {"self", "cls"} and f"{{{arg.arg}}}" not in path:
                    body_param = annotation
        return RouteInfo(
            method=method.upper(),
            # A route declared on `router = APIRouter(prefix="/api")` is served
            # at the prefixed path, so resolve it here rather than at call time.
            path=_join_prefix(self._prefix_for(owner), path),
            file=self.relative_path,
            line=node.lineno,
            function=node.name,
            source="static",
            status_codes=[status_code] if status_code else [],
            parameters=parameters,
            request_body=body_param,
            response_model=response_model,
            summary=_keyword_str(decorator, "summary"),
        )

    def _prefix_for(self, owner: str | None) -> str:
        if owner is None:
            return ""
        return self.router_prefixes.get(owner, "")


def _join_prefix(prefix: str, path: str) -> str:
    prefix = (prefix or "").rstrip("/")
    path = path or "/"
    if not prefix:
        return path if path.startswith("/") else f"/{path}"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{prefix}{path}" if path != "/" else prefix or "/"


def _callee_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _first_string_arg(call: ast.Call) -> str | None:
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    keyword = _keyword_str(call, "path")
    return keyword


def _keyword_str(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str):
                return keyword.value.value
    return None


def _keyword_int(call: ast.Call, name: str) -> int | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, int):
                return keyword.value.value
    return None


def _keyword_name(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return _annotation_name(keyword.value)
    return None


def _keyword_list(call: ast.Call, name: str) -> list[str] | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
            values = [
                element.value
                for element in keyword.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
            return values or None
    return None


def _annotation_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _annotation_name(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def discover_routes_in_file(path: Path, relative_path: str) -> tuple[list[RouteInfo], set[str], set[str]]:
    """Returns (routes, app_object_names, router_names) for one file."""
    source = read_text(path)
    if not source or "def " not in source:
        return [], set(), set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _regex_fallback(source, relative_path), set(), set()

    visitor = _RouteVisitor(relative_path)
    visitor.visit(tree)

    # Apply prefixes contributed by include_router(prefix=...).
    extra_prefix: dict[str, str] = {}
    for router, prefix in visitor.included:
        if prefix:
            extra_prefix[router] = prefix
    if extra_prefix:
        # Routes were already prefixed with the router's own prefix; the
        # include prefix stacks in front of it.
        pass
    return visitor.routes, visitor.app_names, visitor.router_names


_ROUTE_RE = re.compile(
    r"@(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\.(?P<method>get|post|put|delete|patch|head|options)\(\s*[\"'](?P<path>[^\"']+)[\"']"
)


def _regex_fallback(source: str, relative_path: str) -> list[RouteInfo]:
    routes: list[RouteInfo] = []
    for number, line in enumerate(source.splitlines(), start=1):
        match = _ROUTE_RE.search(line)
        if match:
            routes.append(
                RouteInfo(
                    method=match.group("method").upper(),
                    path=match.group("path"),
                    file=relative_path,
                    line=number,
                    source="static",
                )
            )
    return routes


def discover_routes(root: Path) -> tuple[list[RouteInfo], dict]:
    """Walk a project and collect every statically-declared route."""
    routes: list[RouteInfo] = []
    app_files: list[str] = []
    app_objects: dict[str, str] = {}
    include_prefixes: list[tuple[str, str, str]] = []

    for path in iter_files(root):
        if path.suffix != ".py":
            continue
        relative = relative_posix(path, root)
        file_routes, apps, _routers = discover_routes_in_file(path, relative)
        if apps:
            app_files.append(relative)
            app_objects[relative] = sorted(apps)[0]
        if file_routes:
            routes.extend(file_routes)
        source = read_text(path)
        if "include_router" in source:
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            visitor = _RouteVisitor(relative)
            visitor.visit(tree)
            for router, prefix in visitor.included:
                if prefix:
                    include_prefixes.append((relative, router, prefix))

    # Second pass: routes defined on a router that was included with a prefix
    # in another module need that prefix applied.
    if include_prefixes:
        module_prefix: dict[str, str] = {}
        for _caller, router, prefix in include_prefixes:
            module_prefix[router] = prefix
        adjusted: list[RouteInfo] = []
        for route in routes:
            module_name = Path(route.file).stem
            prefix = module_prefix.get(module_name) or module_prefix.get("router") or ""
            if prefix and not route.path.startswith(prefix) and route.file != "main.py":
                route = route.model_copy(update={"path": _join_prefix(prefix, route.path)})
            adjusted.append(route)
        routes = adjusted

    deduped: dict[str, RouteInfo] = {}
    for route in routes:
        deduped.setdefault(f"{route.method} {route.path}", route)

    info = {
        "app_files": app_files,
        "app_objects": app_objects,
        "include_prefixes": include_prefixes,
    }
    return sorted(deduped.values(), key=lambda r: (r.path, r.method)), info


def routes_from_openapi(schema: dict) -> list[RouteInfo]:
    """Convert a live `/openapi.json` document into RouteInfo records."""
    routes: list[RouteInfo] = []
    for path, operations in (schema.get("paths") or {}).items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            responses = operation.get("responses") or {}
            status_codes = []
            for code in responses:
                try:
                    status_codes.append(int(code))
                except (TypeError, ValueError):
                    continue
            parameters = [
                p.get("name", "")
                for p in (operation.get("parameters") or [])
                if isinstance(p, dict)
            ]
            body = None
            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content") or {}
                for media in content.values():
                    ref = (media.get("schema") or {}).get("$ref")
                    if ref:
                        body = ref.rsplit("/", 1)[-1]
                        break
            routes.append(
                RouteInfo(
                    method=method.upper(),
                    path=path,
                    file=(operation.get("x-source-file") or "openapi"),
                    line=0,
                    function=operation.get("operationId"),
                    source="openapi",
                    status_codes=sorted(status_codes),
                    parameters=parameters,
                    request_body=body,
                    summary=operation.get("summary"),
                )
            )
    return routes


def merge_routes(static_routes: list[RouteInfo], runtime_routes: list[RouteInfo]) -> list[RouteInfo]:
    """Runtime wins on contract details; static wins on file/line provenance."""
    merged: dict[str, RouteInfo] = {r.signature: r for r in static_routes}
    for runtime in runtime_routes:
        existing = merged.get(runtime.signature)
        if existing is None:
            merged[runtime.signature] = runtime
            continue
        merged[runtime.signature] = existing.model_copy(
            update={
                "status_codes": sorted(set(existing.status_codes) | set(runtime.status_codes)),
                "parameters": existing.parameters or runtime.parameters,
                "request_body": existing.request_body or runtime.request_body,
                "summary": existing.summary or runtime.summary,
                "source": "openapi",
            }
        )
    return sorted(merged.values(), key=lambda r: (r.path, r.method))


def sample_value_for(name: str) -> str:
    """Pick a plausible path-parameter value for probing."""
    lowered = name.lower()
    if lowered.endswith("_id") or lowered == "id" or lowered.endswith("id"):
        return "1"
    if "uuid" in lowered:
        return "00000000-0000-0000-0000-000000000000"
    if "email" in lowered:
        return "user@example.com"
    if "date" in lowered:
        return "2024-01-01"
    if any(token in lowered for token in ("count", "limit", "offset", "page", "num", "qty")):
        return "1"
    return "1"


PATH_PARAM = re.compile(r"\{([^}/]+)\}")


def concretize_path(path: str) -> str:
    """`/users/{user_id}` -> `/users/1` so the endpoint can actually be called."""
    def replace(match):
        return sample_value_for(match.group(1).split(":")[0])

    return PATH_PARAM.sub(replace, path)
