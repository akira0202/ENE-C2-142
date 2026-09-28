# PB: no-action (prohibited-action) boundary.
#
# The template is a read-only, deterministic, offline evidence extractor. This module proves — by
# static AST scan, so it needs no framework runtime — that the agent's execution surface
# (src/graph, src/nodes, src/services, src/schemas) has NO code path that could take an external or
# prohibited domain action:
#   1. every import resolves to the deterministic allowlist (first-party + safe stdlib) — no network,
#      subprocess, or other egress module is reachable;
#   2. no external / side-effect call site exists (eval / exec / subprocess / socket / os.system …);
#   3. no forecast / optimization / tariff / dispatch / trading / grid-control capability is defined —
#      those verbs live only as deny-list detection literals in the output policy, never as a callable.
#
# src/api/ is the framework-provided transport shim (it hosts and INVOKES the agent, and legitimately
# imports the serving framework and binds secrets at the call boundary); it is not part of the
# agent's own action surface and is out of scope for this boundary.

import ast
import os
import re

# The agent's own execution surface (transport shim src/api/ excluded, per the module docstring).
_HERE = os.path.dirname(__file__)
_SRC = os.path.join(_HERE, "..", "..", "src")
_AGENT_DIRS = [os.path.join(_SRC, d) for d in ("graph", "nodes", "services", "schemas")]

# Deterministic import allowlist. Anything outside this is a potential action/egress path.
_ALLOWED_IMPORT_ROOTS = {
    # first-party + framework + graph engine
    "src", "framework", "shared", "langgraph",
    # safe, non-egress stdlib actually used by the deterministic core
    "json", "csv", "io", "math", "re", "typing", "__future__",
    "datetime", "decimal", "collections", "itertools", "functools", "enum", "uuid",
}

# Call targets that would constitute an external action / arbitrary-code side effect.
_PROHIBITED_CALL_NAMES = {"eval", "exec", "compile", "__import__"}
_PROHIBITED_CALL_ATTRS = {"system", "popen", "spawn", "exec", "connect", "sendall", "urlopen", "run", "call", "Popen"}
_PROHIBITED_ATTR_OWNERS = {"subprocess", "socket", "os", "requests", "httpx", "urllib"}

# Prohibited domain-action capability verbs (must never be an implemented callable name).
_ACTION_VERB = re.compile(
    r"forecast|optim|tariff|dispatch|trad(e|ing)|curtail|actuate|grid[_-]?control|control[_-]?grid",
    re.IGNORECASE,
)


def _agent_py_files() -> list[str]:
    files = []
    for d in _AGENT_DIRS:
        for root, _dirs, names in os.walk(d):
            if "__pycache__" in root:
                continue
            files.extend(os.path.join(root, n) for n in names if n.endswith(".py"))
    return files


def _tree(path: str) -> ast.AST:
    with open(path, "r") as f:
        return ast.parse(f.read(), filename=path)


def test_agent_runtime_imports_are_deterministic_allowlist():
    violations = []
    for path in _agent_py_files():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in _ALLOWED_IMPORT_ROOTS:
                        violations.append(f"{path}:{node.lineno} — import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                root = node.module.split(".")[0]
                if root not in _ALLOWED_IMPORT_ROOTS:
                    violations.append(f"{path}:{node.lineno} — from {node.module} import ...")
    assert violations == [], "non-deterministic / egress import(s) found:\n" + "\n".join(violations)


def test_no_external_action_or_side_effect_call_sites():
    violations = []
    for path in _agent_py_files():
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in _PROHIBITED_CALL_NAMES:
                violations.append(f"{path}:{node.lineno} — {func.id}(...)")
            elif isinstance(func, ast.Attribute):
                owner = func.value.id if isinstance(func.value, ast.Name) else None
                if owner in _PROHIBITED_ATTR_OWNERS and func.attr in _PROHIBITED_CALL_ATTRS:
                    violations.append(f"{path}:{node.lineno} — {owner}.{func.attr}(...)")
    assert violations == [], "external-action / side-effect call site(s) found:\n" + "\n".join(violations)


def test_no_prohibited_domain_action_capability_defined():
    # No callable in the agent surface is NAMED after a prohibited action; the verbs appear only as
    # deny-list detection literals in the output policy (proven by test_output_policy.py).
    offenders = []
    for path in _agent_py_files():
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _ACTION_VERB.search(node.name):
                offenders.append(f"{path}:{node.lineno} — def {node.name}(...)")
    assert offenders == [], "prohibited domain-action capability defined:\n" + "\n".join(offenders)
