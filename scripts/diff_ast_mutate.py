#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/diff_ast_mutate.py

Deterministic diff-line AST mutation testing tool (TD-134).
Pure Python 3.14 standard library + sibling bounded_process.run_bounded.

Exit codes:
  0  PASS (or PASS_NO_MUTANTS, or --list dry-run succeeded)
  1  FAIL (one or more SURVIVED mutants remain after --accept exemptions)
  2  ERROR / FAIL-CLOSED (baseline failed, cap exceeded, stale/invalid accept file,
     test-map error, timeout, syntax-invalid mutant, restore mismatch, git/patch/args error)
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import bounded_process  # noqa: E402

TOOL_NAME = "diff_ast_mutate.py"
TOOL_VERSION = "1.1.0"
SCHEMA_VERSION = 1

DEFAULT_MAX_MUTANTS = 120
DEFAULT_PER_MUTANT_TIMEOUT = 60.0
DEFAULT_TOTAL_TIMEOUT = 900.0
DEFAULT_BASELINE_TIMEOUT = 120.0
_DEFAULT_MONOTONIC: Callable[[], float] = time.monotonic


def _matches_qualname(qualname: str, patterns: list[str]) -> bool:
    """Return True if qualname matches any case-sensitive fnmatchcase glob pattern."""
    return any(fnmatch.fnmatchcase(qualname, pat) for pat in patterns)

HUNK_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")
DIFF_PLUS_RE = re.compile(r"^\+\+\+\s+(?:b/)?(.+)$")

NOISE_CALL_NAMES = frozenset({"print", "warn"})
NOISE_CALL_ATTRS = frozenset({
    "logging.debug", "logging.info", "logging.warning", "logging.warn",
    "logging.error", "logging.critical", "logging.exception",
    "logger.debug", "logger.info", "logger.warning", "logger.warn",
    "logger.error", "logger.critical", "logger.exception",
    "log.debug", "log.info", "log.warning", "log.warn",
    "log.error", "log.critical", "log.exception",
    "warnings.warn", "pprint.pprint", "pprint.pformat",
    "sys.stdout.write", "sys.stderr.write",
})

CMP_EQ_RE = re.compile(r"(!=|==)")
CMP_BND_RE = re.compile(r"(<=|>=|<|>)")
CMP_IN_RE = re.compile(r"\b(not\s+in|in)\b")
CMP_IS_RE = re.compile(r"\b(is\s+not|is)\b")
BOOL_OP_RE = re.compile(r"\b(and|or)\b")
ARITH_BIN_RE = re.compile(r"(\+|-)")
ARITH_AUG_RE = re.compile(r"(\+=|-=)")


class ToolError(Exception):
    """Fail-closed operational error mapped to exit code 2."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class MutantCandidate:
    id: str
    display_id: str
    file: str
    qualname: str
    lineno: int
    end_lineno: int
    col_offset: int
    op: str
    original: str
    mutated: str
    start_byte: int
    end_byte: int
    replacement_bytes: bytes


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tool_sha256() -> str:
    try:
        return _sha256_bytes(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))
    except OSError:
        return ""


def _force_rmtree(path: Path) -> None:
    if not path.exists():
        return

    def _on_err(func: Any, p: str, _exc: Any) -> None:
        try:
            os.chmod(p, stat.S_IWRITE)
        except OSError:
            pass
        func(p)

    shutil.rmtree(path, onexc=_on_err)


def _clean_git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git(repo: Path, args: list[str], *, env: dict[str, str] | None = None, timeout: float = 120.0) -> bytes:
    git_env = env if env is not None else _clean_git_env()
    res = bounded_process.run_bounded(
        ["git", "--no-optional-locks", "--no-replace-objects", "-C", str(repo), *args],
        str(repo),
        timeout,
        env=git_env,
        merge_stderr=False,
    )
    if res.launch_error is not None:
        raise ToolError("GIT_ERROR", f"git launch failed: {res.launch_error}")
    if res.timed_out:
        raise ToolError("GIT_ERROR", f"git timed out: {' '.join(args)}")
    if res.returncode != 0:
        err_txt = res.stderr.decode("utf-8", errors="replace").strip()
        raise ToolError("GIT_ERROR", f"git {' '.join(args)} failed (rc={res.returncode}): {err_txt}")
    return res.stdout


def _posix_rel(path_str: str) -> str:
    norm = path_str.replace("\\", "/").lstrip("./")
    while "//" in norm:
        norm = norm.replace("//", "/")
    return norm


def _is_default_excluded_test(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


def _filter_rel_paths(
    candidates: dict[str, set[int] | None],
    *,
    include_globs: list[str],
    exclude_globs: list[str],
    explicit_files: bool,
) -> dict[str, set[int] | None]:
    out: dict[str, set[int] | None] = {}
    for raw_rel, lines in sorted(candidates.items()):
        rel = _posix_rel(raw_rel)
        if not rel.endswith(".py"):
            continue
        if include_globs:
            if not any(fnmatch.fnmatch(rel, g) for g in include_globs):
                continue
        elif not explicit_files and _is_default_excluded_test(rel):
            continue
        if exclude_globs and any(fnmatch.fnmatch(rel, g) for g in exclude_globs):
            continue
        out[rel] = lines
    return out


def parse_unified_diff(diff_text: str) -> dict[str, set[int]]:
    """Parse unified diff (`-U0` or any `-U`) into {posix_rel_path: set_of_1based_added_lines}."""
    file_lines: dict[str, set[int]] = {}
    cur_file: str | None = None
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            cur_file = None
            continue
        if raw_line.startswith("--- "):
            continue
        m_plus = DIFF_PLUS_RE.match(raw_line)
        if m_plus:
            target = m_plus.group(1).strip()
            if target == "/dev/null":
                cur_file = None
            else:
                if target.startswith('"') and target.endswith('"'):
                    target = target[1:-1]
                cur_file = _posix_rel(target)
                file_lines.setdefault(cur_file, set())
            continue
        m_hunk = HUNK_RE.match(raw_line)
        if m_hunk and cur_file is not None:
            start = int(m_hunk.group(1))
            count = int(m_hunk.group(2)) if m_hunk.group(2) is not None else 1
            if count > 0:
                file_lines[cur_file].update(range(start, start + count))
    return {k: v for k, v in file_lines.items() if v}


def _line_offsets(raw_bytes: bytes) -> list[int]:
    starts: list[int] = []
    pos = 0
    for ln in raw_bytes.splitlines(keepends=True):
        starts.append(pos)
        pos += len(ln)
    if not starts:
        starts.append(0)
    return starts


def _byte_pos(starts: list[int], lineno: int, col_offset: int) -> int:
    return starts[lineno - 1] + col_offset


def _node_span(starts: list[int], node: ast.AST) -> tuple[int, int] | None:
    lineno = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    end_lineno = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if lineno is None or col is None or end_lineno is None or end_col is None:
        return None
    return _byte_pos(starts, lineno, col), _byte_pos(starts, end_lineno, end_col)


def _dotted_name(expr: ast.AST) -> str:
    parts: list[str] = []
    cur: ast.AST | None = expr
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _is_noise_call(call: ast.Call) -> bool:
    dn = _dotted_name(call.func)
    if not dn:
        return False
    return dn in NOISE_CALL_NAMES or dn in NOISE_CALL_ATTRS


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left, right = test.left, test.comparators[0]
    pairs = ((left, right), (right, left))
    return any(
        isinstance(a, ast.Name) and a.id == "__name__"
        and isinstance(b, ast.Constant) and b.value == "__main__"
        for a, b in pairs
    )


def _is_type_checking_guard(node: ast.If) -> bool:
    dn = _dotted_name(node.test)
    return dn in ("TYPE_CHECKING", "typing.TYPE_CHECKING")


def _contains_str_or_bytes(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.JoinedStr):
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, (str, bytes)):
            return True
    return False


def _canonical_unparse(node_or_code: ast.AST | str) -> str:
    if isinstance(node_or_code, ast.AST):
        return ast.unparse(node_or_code)
    try:
        parsed = ast.parse(node_or_code, mode="eval")
        return ast.unparse(parsed.body)
    except SyntaxError:
        try:
            parsed = ast.parse(node_or_code, mode="exec")
            return ast.unparse(parsed)
        except SyntaxError:
            return node_or_code.strip()


def _make_mutant_id(
    rel_path: str,
    qualname: str,
    op_name: str,
    norm_orig: str,
    norm_mut: str,
    occ_idx: int,
) -> tuple[str, str]:
    payload = f"{rel_path}\n{qualname}\n{op_name}\n{norm_orig}\n{norm_mut}\n{occ_idx}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:10]
    return f"M-{digest}", f"{rel_path}::{qualname}::{op_name}#{occ_idx}"


def _find_gap_operator(
    raw_bytes: bytes,
    left_end: int,
    right_start: int,
    pattern: re.Pattern[str],
) -> tuple[int, int, str] | None:
    if left_end >= right_start:
        return None
    gap_bytes = raw_bytes[left_end:right_start]
    gap_text = gap_bytes.decode("utf-8", errors="replace")
    m = pattern.search(gap_text)
    if m is None:
        return None
    op_start = left_end + len(gap_text[:m.start()].encode("utf-8"))
    op_end = left_end + len(gap_text[:m.end()].encode("utf-8"))
    return op_start, op_end, m.group(1)


class _FileMutantCollector:
    """Deterministic AST scanner with scope-local occurrence numbering & diff-line filtering."""

    def __init__(self, rel_path: str, raw_bytes: bytes, changed_lines: set[int] | None) -> None:
        self.rel_path = rel_path
        self.raw_bytes = raw_bytes
        self.starts = _line_offsets(raw_bytes)
        self.changed_lines = changed_lines
        self.scope_stack: list[str] = []
        self.occ_counts: dict[tuple[str, str, str], int] = {}
        self.mutants: list[MutantCandidate] = []
        self.skipped_nodes = 0
        self.invalid_count = 0

    def _qualname(self) -> str:
        return ".".join(self.scope_stack) if self.scope_stack else "<module>"

    def _next_occ(self, qualname: str, op_name: str, norm_orig: str) -> int:
        key = (qualname, op_name, norm_orig)
        val = self.occ_counts.get(key, 0) + 1
        self.occ_counts[key] = val
        return val

    def _in_diff_scope(self, lineno: int, end_lineno: int) -> bool:
        if self.changed_lines is None:
            return True
        return any(ln in self.changed_lines for ln in range(lineno, end_lineno + 1))

    def _emit_span(
        self,
        *,
        qualname: str,
        op_name: str,
        lineno: int,
        end_lineno: int,
        col_offset: int,
        start_byte: int,
        end_byte: int,
        replacement_bytes: bytes,
        norm_orig: str,
        norm_mut: str,
    ) -> None:
        occ_idx = self._next_occ(qualname, op_name, norm_orig)
        if not self._in_diff_scope(lineno, end_lineno):
            return
        mutated_full = self.raw_bytes[:start_byte] + replacement_bytes + self.raw_bytes[end_byte:]
        try:
            ast.parse(mutated_full.decode("utf-8"), filename=self.rel_path)
        except (SyntaxError, UnicodeDecodeError):
            self.invalid_count += 1
            return
        mid, disp = _make_mutant_id(self.rel_path, qualname, op_name, norm_orig, norm_mut, occ_idx)
        self.mutants.append(
            MutantCandidate(
                id=mid,
                display_id=disp,
                file=self.rel_path,
                qualname=qualname,
                lineno=lineno,
                end_lineno=end_lineno,
                col_offset=col_offset,
                op=op_name,
                original=norm_orig,
                mutated=norm_mut,
                start_byte=start_byte,
                end_byte=end_byte,
                replacement_bytes=replacement_bytes,
            )
        )

    def collect(self, tree: ast.Module) -> None:
        self._visit_block(tree.body)

    def _visit_block(self, stmts: list[ast.stmt]) -> None:
        for idx, stmt in enumerate(stmts):
            if idx == 0 and _is_docstring_stmt(stmt):
                self.skipped_nodes += 1
                continue
            self._visit_stmt(stmt)

    def _visit_stmt(self, stmt: ast.stmt) -> None:
        qual = self._qualname()
        if isinstance(stmt, ast.ClassDef):
            for dec in stmt.decorator_list:
                self._visit_expr(dec)
            for base in stmt.bases:
                self._visit_expr(base)
            self.scope_stack.append(stmt.name)
            try:
                self._visit_block(stmt.body)
            finally:
                self.scope_stack.pop()
            return

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in stmt.decorator_list:
                self._visit_expr(dec)
            for dflt in stmt.args.defaults:
                self._visit_expr(dflt)
            for dflt in stmt.args.kw_defaults:
                if dflt is not None:
                    self._visit_expr(dflt)
            self.scope_stack.append(stmt.name)
            try:
                self._visit_block(stmt.body)
            finally:
                self.scope_stack.pop()
            return

        if isinstance(stmt, ast.If):
            if _is_main_guard(stmt) or _is_type_checking_guard(stmt):
                self.skipped_nodes += 1
                return
            self._emit_branch_test_mutants(stmt.test, allow_negate=True)
            self._visit_expr(
                stmt.test,
                skip_const_bool=(isinstance(stmt.test, ast.Constant) and isinstance(stmt.test.value, bool)),
            )
            self._visit_block(stmt.body)
            self._visit_block(stmt.orelse)
            return

        if isinstance(stmt, ast.While):
            self._emit_branch_test_mutants(stmt.test, allow_negate=False)
            self._visit_expr(
                stmt.test,
                skip_const_bool=(isinstance(stmt.test, ast.Constant) and isinstance(stmt.test.value, bool)),
            )
            self._visit_block(stmt.body)
            self._visit_block(stmt.orelse)
            return

        if isinstance(stmt, ast.Return):
            if stmt.value is not None and not (isinstance(stmt.value, ast.Constant) and stmt.value.value is None):
                span = _node_span(self.starts, stmt)
                if span is not None:
                    norm_orig = _canonical_unparse(stmt)
                    self._emit_span(
                        qualname=qual,
                        op_name="RET_NONE_OR_EMPTY",
                        lineno=stmt.lineno,
                        end_lineno=stmt.end_lineno or stmt.lineno,
                        col_offset=stmt.col_offset,
                        start_byte=span[0],
                        end_byte=span[1],
                        replacement_bytes=b"return None",
                        norm_orig=norm_orig,
                        norm_mut="return None",
                    )
                self._visit_expr(stmt.value)
            return

        if isinstance(stmt, ast.AugAssign):
            if isinstance(stmt.op, (ast.Add, ast.Sub)) and not _contains_str_or_bytes(stmt.value):
                ts = _node_span(self.starts, stmt.target)
                vs = _node_span(self.starts, stmt.value)
                full_s = _node_span(self.starts, stmt)
                if ts is not None and vs is not None and full_s is not None:
                    found = _find_gap_operator(self.raw_bytes, ts[1], vs[0], ARITH_AUG_RE)
                    if found is not None:
                        op_s, op_e, op_txt = found
                        new_op = "-=" if op_txt == "+=" else "+="
                        mut_snippet = (
                            self.raw_bytes[full_s[0]:op_s]
                            + new_op.encode("utf-8")
                            + self.raw_bytes[op_e:full_s[1]]
                        ).decode("utf-8", errors="replace")
                        self._emit_span(
                            qualname=qual,
                            op_name="AUG_OR_BIN_ARITH",
                            lineno=stmt.lineno,
                            end_lineno=stmt.end_lineno or stmt.lineno,
                            col_offset=stmt.col_offset,
                            start_byte=op_s,
                            end_byte=op_e,
                            replacement_bytes=new_op.encode("utf-8"),
                            norm_orig=_canonical_unparse(stmt),
                            norm_mut=_canonical_unparse(mut_snippet),
                        )
            self._visit_expr(stmt.value)
            return

        if isinstance(stmt, ast.AnnAssign):
            if stmt.value is not None:
                self._visit_expr(stmt.value)
            return

        if isinstance(stmt, ast.Assign):
            self._visit_expr(stmt.value)
            return

        if isinstance(stmt, ast.Raise):
            self.skipped_nodes += 1
            return

        if isinstance(stmt, ast.Expr):
            if isinstance(stmt.value, ast.Call):
                if _is_noise_call(stmt.value):
                    self.skipped_nodes += 1
                    return
                span = _node_span(self.starts, stmt)
                if span is not None:
                    self._emit_span(
                        qualname=qual,
                        op_name="STMT_CALL_DELETE",
                        lineno=stmt.lineno,
                        end_lineno=stmt.end_lineno or stmt.lineno,
                        col_offset=stmt.col_offset,
                        start_byte=span[0],
                        end_byte=span[1],
                        replacement_bytes=b"pass",
                        norm_orig=_canonical_unparse(stmt),
                        norm_mut="pass",
                    )
            self._visit_expr(stmt.value)
            return

        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.stmt):
                self._visit_stmt(child)
            elif isinstance(child, ast.expr):
                self._visit_expr(child)

    def _emit_branch_test_mutants(self, test: ast.expr, *, allow_negate: bool) -> None:
        qual = self._qualname()
        span = _node_span(self.starts, test)
        if span is None:
            return
        t_lineno = test.lineno
        t_end = test.end_lineno or test.lineno
        t_col = test.col_offset
        norm_orig = _canonical_unparse(test)
        if not (isinstance(test, ast.Constant) and test.value is False):
            self._emit_span(
                qualname=qual,
                op_name="IF_COND_FALSE",
                lineno=t_lineno,
                end_lineno=t_end,
                col_offset=t_col,
                start_byte=span[0],
                end_byte=span[1],
                replacement_bytes=b"False",
                norm_orig=norm_orig,
                norm_mut="False",
            )
        if allow_negate:
            skip_negate = (
                isinstance(test, ast.Compare)
                or (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not))
                or (isinstance(test, ast.Constant) and isinstance(test.value, bool))
            )
            if not skip_negate:
                orig_src = self.raw_bytes[span[0]:span[1]].decode("utf-8", errors="replace")
                rep_src = f"not ({orig_src})"
                self._emit_span(
                    qualname=qual,
                    op_name="IF_NEGATE_COND",
                    lineno=t_lineno,
                    end_lineno=t_end,
                    col_offset=t_col,
                    start_byte=span[0],
                    end_byte=span[1],
                    replacement_bytes=rep_src.encode("utf-8"),
                    norm_orig=norm_orig,
                    norm_mut=_canonical_unparse(rep_src),
                )

    def _visit_expr(self, expr: ast.expr, *, skip_const_bool: bool = False) -> None:
        qual = self._qualname()
        if isinstance(expr, ast.IfExp):
            self._emit_branch_test_mutants(expr.test, allow_negate=True)
            self._visit_expr(expr.test, skip_const_bool=(isinstance(expr.test, ast.Constant) and isinstance(expr.test.value, bool)))
            self._visit_expr(expr.body)
            self._visit_expr(expr.orelse)
            return

        if isinstance(expr, ast.Call):
            if _is_noise_call(expr):
                self.skipped_nodes += 1
                return
            for arg in expr.args:
                self._visit_expr(arg)
            for kw in expr.keywords:
                self._visit_expr(kw.value)
            if not isinstance(expr.func, (ast.Name, ast.Attribute)):
                self._visit_expr(expr.func)
            return

        if isinstance(expr, ast.Compare):
            full_s = _node_span(self.starts, expr)
            if full_s is not None:
                prev_expr: ast.expr = expr.left
                for op, comp in zip(expr.ops, expr.comparators):
                    p_span = _node_span(self.starts, prev_expr)
                    c_span = _node_span(self.starts, comp)
                    if p_span is not None and c_span is not None:
                        self._emit_compare_op(qual, expr, full_s, p_span[1], c_span[0], op)
                    prev_expr = comp
            self._visit_expr(expr.left)
            for comp in expr.comparators:
                self._visit_expr(comp)
            return

        if isinstance(expr, ast.BoolOp):
            full_s = _node_span(self.starts, expr)
            if full_s is not None:
                is_and = isinstance(expr.op, ast.And)
                new_kw = "or" if is_and else "and"
                spans = [_node_span(self.starts, v) for v in expr.values]
                if all(s is not None for s in spans):
                    pieces: list[bytes] = []
                    cur_pos = full_s[0]
                    ok = True
                    for idx in range(len(expr.values) - 1):
                        s_cur = spans[idx]
                        s_nxt = spans[idx + 1]
                        assert s_cur is not None and s_nxt is not None
                        found = _find_gap_operator(self.raw_bytes, s_cur[1], s_nxt[0], BOOL_OP_RE)
                        if found is None:
                            ok = False
                            break
                        pieces.append(self.raw_bytes[cur_pos:found[0]])
                        pieces.append(new_kw.encode("utf-8"))
                        cur_pos = found[1]
                    if ok:
                        pieces.append(self.raw_bytes[cur_pos:full_s[1]])
                        raw_rep = b"(" + b"".join(pieces) + b")"
                        self._emit_span(
                            qualname=qual,
                            op_name="BOOL_AND_OR",
                            lineno=expr.lineno,
                            end_lineno=expr.end_lineno or expr.lineno,
                            col_offset=expr.col_offset,
                            start_byte=full_s[0],
                            end_byte=full_s[1],
                            replacement_bytes=raw_rep,
                            norm_orig=_canonical_unparse(expr),
                            norm_mut=_canonical_unparse(raw_rep.decode("utf-8", errors="replace")),
                        )
                    drop_val_str = "True" if is_and else "False"
                    drop_val_bool = True if is_and else False
                    for val_node in expr.values:
                        if isinstance(val_node, ast.Constant) and val_node.value is drop_val_bool:
                            continue
                        vs = _node_span(self.starts, val_node)
                        if vs is not None:
                            mut_full = (
                                self.raw_bytes[full_s[0]:vs[0]]
                                + drop_val_str.encode("utf-8")
                                + self.raw_bytes[vs[1]:full_s[1]]
                            ).decode("utf-8", errors="replace")
                            self._emit_span(
                                qualname=qual,
                                op_name="BOOL_DROP_OPERAND",
                                lineno=val_node.lineno,
                                end_lineno=val_node.end_lineno or val_node.lineno,
                                col_offset=val_node.col_offset,
                                start_byte=vs[0],
                                end_byte=vs[1],
                                replacement_bytes=drop_val_str.encode("utf-8"),
                                norm_orig=_canonical_unparse(expr),
                                norm_mut=_canonical_unparse(mut_full),
                            )
            for val in expr.values:
                self._visit_expr(val)
            return

        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
            full_s = _node_span(self.starts, expr)
            op_s = _node_span(self.starts, expr.operand)
            if full_s is not None and op_s is not None:
                inner = self.raw_bytes[op_s[0]:op_s[1]].decode("utf-8", errors="replace")
                rep_src = f"({inner})" if isinstance(expr.operand, (ast.BoolOp, ast.BinOp, ast.Compare, ast.IfExp, ast.UnaryOp)) else inner
                self._emit_span(
                    qualname=qual,
                    op_name="UNARY_DROP_NOT",
                    lineno=expr.lineno,
                    end_lineno=expr.end_lineno or expr.lineno,
                    col_offset=expr.col_offset,
                    start_byte=full_s[0],
                    end_byte=full_s[1],
                    replacement_bytes=rep_src.encode("utf-8"),
                    norm_orig=_canonical_unparse(expr),
                    norm_mut=_canonical_unparse(rep_src),
                )
            self._visit_expr(expr.operand)
            return

        if isinstance(expr, ast.BinOp):
            if isinstance(expr.op, (ast.Add, ast.Sub)) and not (
                _contains_str_or_bytes(expr.left) or _contains_str_or_bytes(expr.right)
            ):
                full_s = _node_span(self.starts, expr)
                ls = _node_span(self.starts, expr.left)
                rs = _node_span(self.starts, expr.right)
                if full_s is not None and ls is not None and rs is not None:
                    found = _find_gap_operator(self.raw_bytes, ls[1], rs[0], ARITH_BIN_RE)
                    if found is not None:
                        op_s, op_e, op_txt = found
                        new_op = "-" if op_txt == "+" else "+"
                        mut_expr = (
                            self.raw_bytes[full_s[0]:op_s]
                            + new_op.encode("utf-8")
                            + self.raw_bytes[op_e:full_s[1]]
                        ).decode("utf-8", errors="replace")
                        self._emit_span(
                            qualname=qual,
                            op_name="AUG_OR_BIN_ARITH",
                            lineno=expr.lineno,
                            end_lineno=expr.end_lineno or expr.lineno,
                            col_offset=expr.col_offset,
                            start_byte=op_s,
                            end_byte=op_e,
                            replacement_bytes=new_op.encode("utf-8"),
                            norm_orig=_canonical_unparse(expr),
                            norm_mut=_canonical_unparse(mut_expr),
                        )
            self._visit_expr(expr.left)
            self._visit_expr(expr.right)
            return

        if isinstance(expr, ast.Constant):
            if type(expr.value) is bool and not skip_const_bool:
                span = _node_span(self.starts, expr)
                if span is not None:
                    new_txt = "False" if expr.value else "True"
                    self._emit_span(
                        qualname=qual,
                        op_name="CONST_BOOL_FLIP",
                        lineno=expr.lineno,
                        end_lineno=expr.end_lineno or expr.lineno,
                        col_offset=expr.col_offset,
                        start_byte=span[0],
                        end_byte=span[1],
                        replacement_bytes=new_txt.encode("utf-8"),
                        norm_orig=_canonical_unparse(expr),
                        norm_mut=new_txt,
                    )
            elif type(expr.value) is int:
                span = _node_span(self.starts, expr)
                if span is not None:
                    val = expr.value
                    new_val = 1 if val == 0 else (0 if val == 1 else val + 1)
                    self._emit_span(
                        qualname=qual,
                        op_name="CONST_INT_DELTA",
                        lineno=expr.lineno,
                        end_lineno=expr.end_lineno or expr.lineno,
                        col_offset=expr.col_offset,
                        start_byte=span[0],
                        end_byte=span[1],
                        replacement_bytes=str(new_val).encode("utf-8"),
                        norm_orig=str(val),
                        norm_mut=str(new_val),
                    )
            return

        if isinstance(expr, ast.Lambda):
            self.scope_stack.append("<lambda>")
            try:
                self._visit_expr(expr.body)
            finally:
                self.scope_stack.pop()
            return

        for child in ast.iter_child_nodes(expr):
            if isinstance(child, ast.expr):
                self._visit_expr(child)
            elif isinstance(child, ast.comprehension):
                self._visit_expr(child.iter)
                for if_c in child.ifs:
                    self._visit_expr(if_c)

    def _emit_compare_op(
        self,
        qual: str,
        full_expr: ast.Compare,
        full_span: tuple[int, int],
        left_end: int,
        right_start: int,
        op: ast.cmpop,
    ) -> None:
        if isinstance(op, (ast.Eq, ast.NotEq)):
            op_name, pat = "CMP_EQ_NE", CMP_EQ_RE
            new_tok = "!=" if isinstance(op, ast.Eq) else "=="
        elif isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
            op_name, pat = "CMP_BOUNDARY", CMP_BND_RE
            if isinstance(op, ast.Lt):
                new_tok = "<="
            elif isinstance(op, ast.LtE):
                new_tok = "<"
            elif isinstance(op, ast.Gt):
                new_tok = ">="
            else:
                new_tok = ">"
        elif isinstance(op, (ast.In, ast.NotIn)):
            op_name, pat = "CMP_IN_NOTIN", CMP_IN_RE
            new_tok = "not in" if isinstance(op, ast.In) else "in"
        elif isinstance(op, (ast.Is, ast.IsNot)):
            op_name, pat = "CMP_IS_ISNOT", CMP_IS_RE
            new_tok = "is not" if isinstance(op, ast.Is) else "is"
        else:
            return

        found = _find_gap_operator(self.raw_bytes, left_end, right_start, pat)
        if found is None:
            return
        op_s, op_e, _ = found
        mut_expr = (
            self.raw_bytes[full_span[0]:op_s]
            + new_tok.encode("utf-8")
            + self.raw_bytes[op_e:full_span[1]]
        ).decode("utf-8", errors="replace")
        self._emit_span(
            qualname=qual,
            op_name=op_name,
            lineno=full_expr.lineno,
            end_lineno=full_expr.end_lineno or full_expr.lineno,
            col_offset=full_expr.col_offset,
            start_byte=op_s,
            end_byte=op_e,
            replacement_bytes=new_tok.encode("utf-8"),
            norm_orig=_canonical_unparse(full_expr),
            norm_mut=_canonical_unparse(mut_expr),
        )


def collect_mutants_for_file(
    rel_path: str,
    raw_bytes: bytes,
    changed_lines: set[int] | None,
) -> tuple[list[MutantCandidate], int, int]:
    """Return (mutants, skipped_nodes, invalid_count) for one Python source file."""
    try:
        text = raw_bytes.decode("utf-8")
        tree = ast.parse(text, filename=rel_path)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise ToolError("TARGET_PARSE_ERROR", f"{rel_path}: {exc}") from None
    collector = _FileMutantCollector(rel_path, raw_bytes, changed_lines)
    collector.collect(tree)
    return collector.mutants, collector.skipped_nodes, collector.invalid_count


def load_accept_file(path: Path | None) -> dict[str, tuple[str, str]]:
    """Validate and return {mutant_id: (reason, batch)} from --accept JSON file."""
    if path is None:
        return {}
    try:
        raw = path.read_bytes().decode("utf-8")
        doc = json.loads(raw)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ToolError("ACCEPT_FILE_INVALID", f"cannot read {path}: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("accepted"), list):
        raise ToolError("ACCEPT_FILE_INVALID", "expected object with schema_version=1 and accepted list")
    out: dict[str, tuple[str, str]] = {}
    for entry in doc["accepted"]:
        if not isinstance(entry, dict):
            raise ToolError("ACCEPT_FILE_INVALID", "accepted entry must be an object")
        mid = entry.get("id")
        reason = entry.get("reason")
        batch = entry.get("batch")
        if not (isinstance(mid, str) and mid.strip() and isinstance(reason, str) and reason.strip() and isinstance(batch, str) and batch.strip()):
            raise ToolError("ACCEPT_FILE_INVALID", "accepted entry requires non-empty id, reason, batch")
        mid = mid.strip()
        if mid in out:
            raise ToolError("ACCEPT_FILE_INVALID", f"duplicate accepted id: {mid}")
        out[mid] = (reason.strip(), batch.strip())
    return out


def load_test_map(path: Path | None) -> tuple[dict[str, list[str]], list[str] | None]:
    """Validate and return (mapping, default_tests) from --test-map JSON file."""
    if path is None:
        return {}, None
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ToolError("TEST_MAP_INVALID", f"cannot read {path}: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("map"), dict):
        raise ToolError("TEST_MAP_INVALID", "expected object with schema_version=1 and map object")
    mapping: dict[str, list[str]] = {}
    for pat, tests in doc["map"].items():
        if not isinstance(pat, str) or not pat.strip() or not isinstance(tests, list) or not tests or not all(isinstance(t, str) and t.strip() for t in tests):
            raise ToolError("TEST_MAP_INVALID", f"invalid mapping entry for {pat!r}")
        mapping[_posix_rel(pat.strip())] = [t.strip() for t in tests]
    default = doc.get("default")
    if default is not None:
        if not isinstance(default, list) or not default or not all(isinstance(t, str) and t.strip() for t in default):
            raise ToolError("TEST_MAP_INVALID", "invalid default test list")
        default = [t.strip() for t in default]
    return mapping, default


def resolve_tests_for_file(
    rel_path: str,
    mapping: dict[str, list[str]],
    default_tests: list[str] | None,
) -> list[str]:
    if rel_path in mapping:
        return list(mapping[rel_path])
    for pat in sorted(mapping):
        if fnmatch.fnmatch(rel_path, pat):
            return list(mapping[pat])
    if default_tests is not None:
        return list(default_tests)
    raise ToolError("TEST_MAP_UNMAPPED", f"no mapped tests for {rel_path}")


def _split_cmd_template(test_cmd: str) -> list[str]:
    try:
        tokens = shlex.split(test_cmd, posix=(os.name != "nt"))
    except ValueError as exc:
        raise ToolError("INVALID_ARGS", f"invalid --test-cmd: {exc}") from None
    cleaned: list[str] = []
    for tok in tokens:
        if len(tok) >= 2 and ((tok[0] == '"' and tok[-1] == '"') or (tok[0] == "'" and tok[-1] == "'")):
            tok = tok[1:-1]
        if tok == "{python}":
            tok = sys.executable
        cleaned.append(tok)
    if not cleaned:
        raise ToolError("INVALID_ARGS", "empty --test-cmd")
    return cleaned


def _build_cmd_argv(template: list[str], tests: list[str] | None) -> list[str]:
    if tests is None:
        return [t for t in template if t != "{tests}"]
    if "{tests}" in template:
        argv: list[str] = []
        for tok in template:
            if tok == "{tests}":
                argv.extend(tests)
            else:
                argv.append(tok)
        return argv
    return [*template, *tests]


def prepare_isolated_copy(
    repo: Path,
    work_parent: Path,
    *,
    scope_kind: str,
    base_ref: str | None,
    target_ref: str | None,
    patch_path: Path | None,
    preserve_git: bool = True,
) -> Path:
    """Create a disposable isolated copy preserving .git (unless preserve_git=False)."""
    iso_dir = Path(tempfile.mkdtemp(prefix="hhai-mutate-", dir=str(work_parent)))
    try:
        has_git = (repo / ".git").exists()
        if preserve_git and has_git:
            _force_rmtree(iso_dir)
            git_env = _clean_git_env()
            res = bounded_process.run_bounded(
                ["git", "--no-optional-locks", "--no-replace-objects", "clone", "-q", "--no-local", "--template=", str(repo), str(iso_dir)],
                str(work_parent),
                300.0,
                env=git_env,
                merge_stderr=True,
            )
            if res.launch_error or res.timed_out or res.returncode != 0:
                raise ToolError("GIT_ERROR", f"isolated clone failed: {res.stdout.decode('utf-8', errors='replace')}")
            if scope_kind == "git_diff" and target_ref is not None:
                _run_git(iso_dir, ["checkout", "-q", target_ref])
            elif scope_kind == "patch" and patch_path is not None:
                if base_ref is not None:
                    _run_git(iso_dir, ["checkout", "-q", base_ref])
                p_res = bounded_process.run_bounded(
                    ["git", "--no-optional-locks", "-C", str(iso_dir), "apply", str(patch_path.resolve())],
                    str(iso_dir),
                    60.0,
                    env=git_env,
                    merge_stderr=True,
                )
                if p_res.launch_error or p_res.timed_out or p_res.returncode != 0:
                    raise ToolError("PATCH_ERROR", f"git apply failed: {p_res.stdout.decode('utf-8', errors='replace')}")
            else:
                # Working-tree mirror: overlay modified + untracked files and remove deleted tracked files
                mod_out = _run_git(repo, ["diff", "--name-only", "-z", "HEAD"]).split(b"\x00")
                unt_out = _run_git(repo, ["ls-files", "--others", "--exclude-standard", "-z"]).split(b"\x00")
                del_out = _run_git(repo, ["diff", "--name-only", "--diff-filter=D", "-z", "HEAD"]).split(b"\x00")
                for bpath in del_out:
                    if not bpath:
                        continue
                    rel = _posix_rel(bpath.decode("utf-8"))
                    (iso_dir / rel).unlink(missing_ok=True)
                for bpath in (*mod_out, *unt_out):
                    if not bpath:
                        continue
                    rel = _posix_rel(bpath.decode("utf-8"))
                    src = repo / rel
                    if src.is_file():
                        dst = iso_dir / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(src.read_bytes())
        else:
            _force_rmtree(iso_dir)
            shutil.copytree(
                repo,
                iso_dir,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"),
            )
        return iso_dir
    except Exception:
        _force_rmtree(iso_dir)
        raise


def _discover_scope(
    repo: Path,
    *,
    scope_kind: str,
    base_ref: str | None,
    target_ref: str | None,
    patch_path: Path | None,
    explicit_files: list[str] | None,
    include_globs: list[str],
    exclude_globs: list[str],
    include_untracked: bool,
) -> tuple[dict[str, set[int] | None], dict[str, bytes], dict[str, Any]]:
    """Return (filtered_file_lines, file_bytes_map, scope_metadata)."""
    file_bytes: dict[str, bytes] = {}
    if scope_kind == "patch":
        assert patch_path is not None
        try:
            patch_text = patch_path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolError("PATCH_ERROR", f"cannot read patch {patch_path}: {exc}") from None
        raw_lines = parse_unified_diff(patch_text)
        filtered = _filter_rel_paths(
            raw_lines, include_globs=include_globs, exclude_globs=exclude_globs, explicit_files=False
        )
        # Apply patch in a tiny isolated clone only if needed to read patched bytes
        with tempfile.TemporaryDirectory(prefix="hhai-mutate-src-", dir=tempfile.gettempdir()) as td:
            src_clone = Path(td) / "src"
            has_git = (repo / ".git").exists()
            if has_git:
                git_env = _clean_git_env()
                res = bounded_process.run_bounded(
                    ["git", "--no-optional-locks", "-C", str(repo), "clone", "-q", "--no-local", "--template=", str(repo), str(src_clone)],
                    td, 120.0, env=git_env, merge_stderr=True,
                )
                if res.returncode != 0:
                    raise ToolError("GIT_ERROR", "patch read clone failed")
                if base_ref is not None:
                    _run_git(src_clone, ["checkout", "-q", base_ref])
                p_res = bounded_process.run_bounded(
                    ["git", "--no-optional-locks", "-C", str(src_clone), "apply", str(patch_path.resolve())],
                    str(src_clone), 60.0, env=git_env, merge_stderr=True,
                )
                if p_res.returncode != 0:
                    raise ToolError("PATCH_ERROR", f"git apply failed: {p_res.stdout.decode('utf-8', errors='replace')}")
                for rel in sorted(filtered):
                    fpath = src_clone / rel
                    if fpath.is_file():
                        file_bytes[rel] = fpath.read_bytes()
            else:
                raise ToolError("GIT_ERROR", "--patch requires a git repository")
        meta = {
            "kind": "patch",
            "base": base_ref or "HEAD",
            "target": None,
            "patch": str(patch_path),
            "files": [],
            "include_glob": include_globs,
            "changed_files": sorted(file_bytes),
        }
        return {k: filtered[k] for k in sorted(file_bytes)}, file_bytes, meta

    if scope_kind == "files":
        assert explicit_files
        raw_map: dict[str, set[int] | None] = {}
        for item in explicit_files:
            rel = _posix_rel(item)
            fpath = repo / rel
            if not fpath.is_file():
                raise ToolError("INVALID_ARGS", f"missing --files target: {rel}")
            raw_map[rel] = None
        filtered = _filter_rel_paths(
            raw_map, include_globs=include_globs, exclude_globs=exclude_globs, explicit_files=True
        )
        for rel in sorted(filtered):
            file_bytes[rel] = (repo / rel).read_bytes()
        meta = {
            "kind": "files",
            "base": None,
            "target": None,
            "patch": None,
            "files": sorted(filtered),
            "include_glob": include_globs,
            "changed_files": sorted(file_bytes),
        }
        return filtered, file_bytes, meta

    # scope_kind == "git_diff"
    assert base_ref is not None
    diff_args = ["diff", "-U0", "--no-color", "--no-ext-diff", base_ref]
    if target_ref is not None:
        diff_args.append(target_ref)
    diff_bytes = _run_git(repo, diff_args)
    raw_lines = parse_unified_diff(diff_bytes.decode("utf-8", errors="replace"))
    raw_map_g: dict[str, set[int] | None] = dict(raw_lines)
    if target_ref is None and include_untracked:
        unt = _run_git(repo, ["ls-files", "--others", "--exclude-standard", "-z"]).split(b"\x00")
        for bpath in unt:
            if not bpath:
                continue
            rel = _posix_rel(bpath.decode("utf-8"))
            if rel.endswith(".py") and (repo / rel).is_file():
                raw_map_g.setdefault(rel, None)
    filtered = _filter_rel_paths(
        raw_map_g, include_globs=include_globs, exclude_globs=exclude_globs, explicit_files=False
    )
    for rel in sorted(filtered):
        if target_ref is not None:
            file_bytes[rel] = _run_git(repo, ["show", f"{target_ref}:{rel}"])
        else:
            fpath = repo / rel
            if fpath.is_file():
                file_bytes[rel] = fpath.read_bytes()
    meta = {
        "kind": "git_diff",
        "base": base_ref,
        "target": target_ref,
        "patch": None,
        "files": [],
        "include_glob": include_globs,
        "changed_files": sorted(file_bytes),
    }
    return {k: filtered[k] for k in sorted(file_bytes)}, file_bytes, meta


def execute_mutation_run(
    *,
    repo: Path,
    scope_kind: str,
    base_ref: str | None = None,
    target_ref: str | None = None,
    patch_path: Path | None = None,
    explicit_files: list[str] | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    include_untracked: bool = True,
    list_only: bool = False,
    test_cmd: str | None = None,
    test_map_path: Path | None = None,
    accept_path: Path | None = None,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
    per_mutant_timeout: float = DEFAULT_PER_MUTANT_TIMEOUT,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    baseline_timeout: float = DEFAULT_BASELINE_TIMEOUT,
    work_parent: Path | None = None,
    preserve_git: bool = True,
    qualnames: list[str] | None = None,
    monotonic_fn: Callable[[], float] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Core orchestrator returning (exit_code, report_dict)."""
    q_filters: list[str] = []
    for raw_q in (qualnames or []):
        if not isinstance(raw_q, str) or not raw_q.strip():
            raise ToolError("INVALID_ARGS", "--qualname pattern must be non-empty")
        q_filters.append(raw_q.strip())

    clock = monotonic_fn if monotonic_fn is not None else _DEFAULT_MONOTONIC
    inc = list(include_globs or [])
    exc = list(exclude_globs or [])
    wp = work_parent or Path(tempfile.gettempdir())
    wp.mkdir(parents=True, exist_ok=True)
    tool_sha = _tool_sha256()

    accept_map = load_accept_file(accept_path)
    test_map, test_default = load_test_map(test_map_path)
    if not list_only and not test_cmd:
        raise ToolError("INVALID_ARGS", "--test-cmd is required unless --list is used")
    cmd_template = _split_cmd_template(test_cmd) if test_cmd else []

    file_lines, file_bytes, scope_meta = _discover_scope(
        repo,
        scope_kind=scope_kind,
        base_ref=base_ref,
        target_ref=target_ref,
        patch_path=patch_path,
        explicit_files=explicit_files,
        include_globs=inc,
        exclude_globs=exc,
        include_untracked=include_untracked,
    )
    scope_meta["qualname_filter"] = list(q_filters)

    all_mutants: list[MutantCandidate] = []
    skipped_nodes = 0
    invalid_count = 0
    for rel in sorted(file_lines):
        m_list, sk, inv = collect_mutants_for_file(rel, file_bytes[rel], file_lines[rel])
        all_mutants.extend(m_list)
        skipped_nodes += sk
        invalid_count += inv

    full_catalog_ids = {m.id for m in all_mutants}
    if q_filters:
        selected_mutants = [m for m in all_mutants if _matches_qualname(m.qualname, q_filters)]
        if not selected_mutants:
            return 2, _build_report(
                tool_sha=tool_sha,
                mode=("list" if list_only else "run"),
                scope=scope_meta,
                baseline={"executed": False, "rc": None, "elapsed_sec": 0.0, "timed_out": False, "cmd": []},
                mutants_records=[],
                skipped_nodes=skipped_nodes,
                invalid_count=invalid_count,
                stale_accepted=[],
                unnecessary_accepted=[],
                out_of_scope_accepted=[],
                exit_code=2,
                verdict="ERROR",
                reason="QUALNAME_UNMATCHED",
            )
    else:
        selected_mutants = all_mutants

    selected_ids = {m.id for m in selected_mutants}
    stale_accepted = sorted(mid for mid in accept_map if mid not in full_catalog_ids)
    out_of_scope_accepted = sorted(mid for mid in accept_map if mid in full_catalog_ids and mid not in selected_ids)
    if stale_accepted:
        return 2, _build_report(
            tool_sha=tool_sha,
            mode=("list" if list_only else "run"),
            scope=scope_meta,
            baseline={"executed": False, "rc": None, "elapsed_sec": 0.0, "timed_out": False, "cmd": []},
            mutants_records=[_listed_record(m, accept_map) for m in selected_mutants],
            skipped_nodes=skipped_nodes,
            invalid_count=invalid_count,
            stale_accepted=stale_accepted,
            unnecessary_accepted=[],
            out_of_scope_accepted=out_of_scope_accepted,
            exit_code=2,
            verdict="ERROR",
            reason="ACCEPT_STALE_ENTRIES",
        )

    # Resolve --test-map early so unmapped files fail closed before executing baseline
    file_tests: dict[str, list[str]] = {}
    if test_map_path is not None:
        for rel in sorted({m.file for m in selected_mutants}):
            file_tests[rel] = resolve_tests_for_file(rel, test_map, test_default)

    if len(selected_mutants) > max_mutants:
        return 2, _build_report(
            tool_sha=tool_sha,
            mode=("list" if list_only else "run"),
            scope=scope_meta,
            baseline={"executed": False, "rc": None, "elapsed_sec": 0.0, "timed_out": False, "cmd": []},
            mutants_records=[_listed_record(m, accept_map) for m in selected_mutants],
            skipped_nodes=skipped_nodes,
            invalid_count=invalid_count,
            stale_accepted=[],
            unnecessary_accepted=[],
            out_of_scope_accepted=out_of_scope_accepted,
            exit_code=2,
            verdict="ERROR",
            reason="MUTANT_CAP_EXCEEDED",
        )

    if invalid_count > 0:
        return 2, _build_report(
            tool_sha=tool_sha,
            mode=("list" if list_only else "run"),
            scope=scope_meta,
            baseline={"executed": False, "rc": None, "elapsed_sec": 0.0, "timed_out": False, "cmd": []},
            mutants_records=[_listed_record(m, accept_map) for m in selected_mutants],
            skipped_nodes=skipped_nodes,
            invalid_count=invalid_count,
            stale_accepted=[],
            unnecessary_accepted=[],
            out_of_scope_accepted=out_of_scope_accepted,
            exit_code=2,
            verdict="ERROR",
            reason="MUTANT_SYNTAX_INVALID",
        )

    if list_only:
        records = [_listed_record(m, accept_map) for m in selected_mutants]
        return 0, _build_report(
            tool_sha=tool_sha,
            mode="list",
            scope=scope_meta,
            baseline={"executed": False, "rc": None, "elapsed_sec": 0.0, "timed_out": False, "cmd": []},
            mutants_records=records,
            skipped_nodes=skipped_nodes,
            invalid_count=0,
            stale_accepted=[],
            unnecessary_accepted=[],
            out_of_scope_accepted=out_of_scope_accepted,
            exit_code=0,
            verdict="PASS",
            reason="LIST_OK",
        )

    if not selected_mutants:
        return 0, _build_report(
            tool_sha=tool_sha,
            mode="run",
            scope=scope_meta,
            baseline={"executed": False, "rc": None, "elapsed_sec": 0.0, "timed_out": False, "cmd": []},
            mutants_records=[],
            skipped_nodes=skipped_nodes,
            invalid_count=0,
            stale_accepted=[],
            unnecessary_accepted=[],
            out_of_scope_accepted=out_of_scope_accepted,
            exit_code=0,
            verdict="PASS_NO_MUTANTS",
            reason="NO_MUTANTS",
        )

    iso_dir = prepare_isolated_copy(
        repo, wp,
        scope_kind=scope_kind,
        base_ref=base_ref,
        target_ref=target_ref,
        patch_path=patch_path,
        preserve_git=preserve_git,
    )
    run_env = os.environ.copy()
    run_env["PYTHONDONTWRITEBYTECODE"] = "1"
    run_start = clock()
    try:
        orig_shas = {rel: _sha256_bytes((iso_dir / rel).read_bytes()) for rel in sorted({m.file for m in selected_mutants})}
        base_tests = sorted({t for tl in file_tests.values() for t in tl}) if test_map_path is not None else None
        base_argv = _build_cmd_argv(cmd_template, base_tests)
        t0 = clock()
        b_res = bounded_process.run_bounded(base_argv, str(iso_dir), baseline_timeout, env=run_env, merge_stderr=True)
        b_elapsed = round(clock() - t0, 3)
        baseline_info = {
            "executed": True,
            "rc": b_res.returncode,
            "elapsed_sec": b_elapsed,
            "timed_out": b_res.timed_out,
            "cmd": base_argv,
        }
        if b_res.launch_error is not None or b_res.timed_out or b_res.returncode != 0:
            records = [_listed_record(m, accept_map, status="NOT_RUN") for m in selected_mutants]
            return 2, _build_report(
                tool_sha=tool_sha,
                mode="run",
                scope=scope_meta,
                baseline=baseline_info,
                mutants_records=records,
                skipped_nodes=skipped_nodes,
                invalid_count=0,
                stale_accepted=[],
                unnecessary_accepted=[],
                out_of_scope_accepted=out_of_scope_accepted,
                exit_code=2,
                verdict="ERROR",
                reason="BASELINE_FAILED",
            )

        records = []
        unnecessary_accepted: list[str] = []
        for idx, m in enumerate(selected_mutants):
            if (clock() - run_start) > total_timeout:
                for rem in selected_mutants[idx:]:
                    records.append(_listed_record(rem, accept_map, status="NOT_RUN"))
                return 2, _build_report(
                    tool_sha=tool_sha,
                    mode="run",
                    scope=scope_meta,
                    baseline=baseline_info,
                    mutants_records=records,
                    skipped_nodes=skipped_nodes,
                    invalid_count=0,
                    stale_accepted=[],
                    unnecessary_accepted=sorted(unnecessary_accepted),
                    out_of_scope_accepted=out_of_scope_accepted,
                    exit_code=2,
                    verdict="ERROR",
                    reason="TOTAL_TIMEOUT_EXCEEDED",
                )

            target_path = iso_dir / m.file
            orig_bytes = file_bytes[m.file]
            mut_bytes = orig_bytes[:m.start_byte] + m.replacement_bytes + orig_bytes[m.end_byte:]
            m_tests = file_tests[m.file] if test_map_path is not None else None
            m_argv = _build_cmd_argv(cmd_template, m_tests)
            m0 = clock()
            try:
                target_path.write_bytes(mut_bytes)
                m_res = bounded_process.run_bounded(m_argv, str(iso_dir), per_mutant_timeout, env=run_env, merge_stderr=True)
            finally:
                target_path.write_bytes(orig_bytes)
                if _sha256_bytes(target_path.read_bytes()) != orig_shas[m.file]:
                    raise ToolError("RESTORE_FAILED", f"failed to restore {m.file} in isolated copy")
            m_elapsed = round(clock() - m0, 3)

            if m_res.launch_error is not None:
                return 2, _build_report(
                    tool_sha=tool_sha,
                    mode="run",
                    scope=scope_meta,
                    baseline=baseline_info,
                    mutants_records=records,
                    skipped_nodes=skipped_nodes,
                    invalid_count=0,
                    stale_accepted=[],
                    unnecessary_accepted=sorted(unnecessary_accepted),
                    out_of_scope_accepted=out_of_scope_accepted,
                    exit_code=2,
                    verdict="ERROR",
                    reason="TEST_LAUNCH_ERROR",
                )

            accept_entry = accept_map.get(m.id)
            if m_res.timed_out:
                status = "CAUGHT_TIMEOUT"
                if accept_entry is not None:
                    unnecessary_accepted.append(m.id)
            elif m_res.returncode != 0:
                status = "CAUGHT"
                if accept_entry is not None:
                    unnecessary_accepted.append(m.id)
            elif accept_entry is not None:
                status = "ACCEPTED"
            else:
                status = "SURVIVED"

            records.append(
                {
                    "id": m.id,
                    "display_id": m.display_id,
                    "file": m.file,
                    "qualname": m.qualname,
                    "lineno": m.lineno,
                    "end_lineno": m.end_lineno,
                    "col_offset": m.col_offset,
                    "op": m.op,
                    "original": m.original,
                    "mutated": m.mutated,
                    "status": status,
                    "rc": m_res.returncode,
                    "elapsed_sec": m_elapsed,
                    "accept_reason": accept_entry[0] if status == "ACCEPTED" and accept_entry else None,
                    "accept_batch": accept_entry[1] if status == "ACCEPTED" and accept_entry else None,
                }
            )

        survived_cnt = sum(1 for r in records if r["status"] == "SURVIVED")
        exit_code = 1 if survived_cnt > 0 else 0
        verdict = "FAIL" if survived_cnt > 0 else "PASS"
        reason = "MUTANTS_SURVIVED" if survived_cnt > 0 else "OK"
        return exit_code, _build_report(
            tool_sha=tool_sha,
            mode="run",
            scope=scope_meta,
            baseline=baseline_info,
            mutants_records=records,
            skipped_nodes=skipped_nodes,
            invalid_count=0,
            stale_accepted=[],
            unnecessary_accepted=sorted(unnecessary_accepted),
            out_of_scope_accepted=out_of_scope_accepted,
            exit_code=exit_code,
            verdict=verdict,
            reason=reason,
        )
    finally:
        _force_rmtree(iso_dir)


def _listed_record(
    m: MutantCandidate,
    accept_map: dict[str, tuple[str, str]],
    *,
    status: str = "LISTED",
) -> dict[str, Any]:
    acc = accept_map.get(m.id)
    return {
        "id": m.id,
        "display_id": m.display_id,
        "file": m.file,
        "qualname": m.qualname,
        "lineno": m.lineno,
        "end_lineno": m.end_lineno,
        "col_offset": m.col_offset,
        "op": m.op,
        "original": m.original,
        "mutated": m.mutated,
        "status": status,
        "rc": None,
        "elapsed_sec": None,
        "accept_reason": acc[0] if acc else None,
        "accept_batch": acc[1] if acc else None,
    }


def _build_report(
    *,
    tool_sha: str,
    mode: str,
    scope: dict[str, Any],
    baseline: dict[str, Any],
    mutants_records: list[dict[str, Any]],
    skipped_nodes: int,
    invalid_count: int,
    stale_accepted: list[str],
    unnecessary_accepted: list[str],
    out_of_scope_accepted: list[str] | None = None,
    exit_code: int,
    verdict: str,
    reason: str,
) -> dict[str, Any]:
    caught = sum(1 for r in mutants_records if r["status"] == "CAUGHT")
    caught_timeout = sum(1 for r in mutants_records if r["status"] == "CAUGHT_TIMEOUT")
    survived = sum(1 for r in mutants_records if r["status"] == "SURVIVED")
    accepted = sum(1 for r in mutants_records if r["status"] == "ACCEPTED")
    oos = list(out_of_scope_accepted or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "tool_sha256": tool_sha,
        "mode": mode,
        "scope": scope,
        "baseline": baseline,
        "summary": {
            "total": len(mutants_records),
            "caught": caught,
            "caught_timeout": caught_timeout,
            "survived": survived,
            "accepted": accepted,
            "invalid": invalid_count,
            "skipped_nodes": skipped_nodes,
            "stale_accepted_count": len(stale_accepted),
            "unnecessary_accepted_count": len(unnecessary_accepted),
            "out_of_scope_accepted_count": len(oos),
            "exit_code": exit_code,
            "verdict": verdict,
            "reason": reason,
        },
        "stale_accepted": stale_accepted,
        "unnecessary_accepted": unnecessary_accepted,
        "out_of_scope_accepted": oos,
        "mutants": mutants_records,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Deterministic diff-line AST mutation tool (TD-134)")
    ap.add_argument("--repo", default=".", help="Repository root path (default: .)")
    scope_grp = ap.add_mutually_exclusive_group()
    scope_grp.add_argument("--base", help="Base git ref/commit for diff scope")
    scope_grp.add_argument("--patch", help="Unified diff patch file for scope")
    scope_grp.add_argument("--files", nargs="+", help="Explicit Python source file paths")
    ap.add_argument("--target", help="Target git ref/commit when using --base (default: working tree)")
    ap.add_argument("--include-glob", action="append", default=[], help="Glob pattern(s) of Python files to include")
    ap.add_argument("--exclude-glob", action="append", default=[], help="Glob pattern(s) of Python files to exclude")
    ap.add_argument("--qualname", action="append", default=[], help="Glob pattern(s) of qualnames to filter (case-sensitive)")
    ap.add_argument("--no-untracked", action="store_true", help="Do not include untracked .py files in working-tree diff")
    ap.add_argument("--list", action="store_true", dest="list_only", help="Dry-run: list mutants without running tests")
    ap.add_argument("--test-cmd", help="Test command template (supports {python} and {tests})")
    ap.add_argument("--test-map", help="JSON mapping changed source paths/globs to pytest test paths")
    ap.add_argument("--accept", help="JSON file of accepted/exempt survived mutant IDs")
    ap.add_argument("--max-mutants", type=int, default=DEFAULT_MAX_MUTANTS, help="Fail-closed cap (default: 120)")
    ap.add_argument("--per-mutant-timeout", type=float, default=DEFAULT_PER_MUTANT_TIMEOUT)
    ap.add_argument("--total-timeout", type=float, default=DEFAULT_TOTAL_TIMEOUT)
    ap.add_argument("--baseline-timeout", type=float, default=DEFAULT_BASELINE_TIMEOUT)
    ap.add_argument("--json-out", help="Write schema v1 JSON report to this path")
    ap.add_argument("--work-parent", help="Directory for disposable isolated copy (default: TEMP)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    try:
        repo = Path(ns.repo).resolve()
        if ns.target and not ns.base:
            ns.base = "HEAD"
        if ns.patch:
            scope_kind = "patch"
        elif ns.files:
            scope_kind = "files"
        elif ns.base:
            scope_kind = "git_diff"
        else:
            raise ToolError("INVALID_ARGS", "must supply --base, --patch, or --files")

        if ns.max_mutants < 0:
            raise ToolError("INVALID_ARGS", "--max-mutants must be >= 0")

        rc, report = execute_mutation_run(
            repo=repo,
            scope_kind=scope_kind,
            base_ref=ns.base,
            target_ref=ns.target,
            patch_path=Path(ns.patch).resolve() if ns.patch else None,
            explicit_files=ns.files,
            include_globs=ns.include_glob,
            exclude_globs=ns.exclude_glob,
            include_untracked=not ns.no_untracked,
            list_only=ns.list_only,
            test_cmd=ns.test_cmd,
            test_map_path=Path(ns.test_map).resolve() if ns.test_map else None,
            accept_path=Path(ns.accept).resolve() if ns.accept else None,
            max_mutants=ns.max_mutants,
            per_mutant_timeout=ns.per_mutant_timeout,
            total_timeout=ns.total_timeout,
            baseline_timeout=ns.baseline_timeout,
            work_parent=Path(ns.work_parent).resolve() if ns.work_parent else None,
            qualnames=ns.qualname,
        )
    except ToolError as exc:
        err_report = _build_report(
            tool_sha=_tool_sha256(),
            mode=("list" if ns.list_only else "run"),
            scope={"kind": "error"},
            baseline={"executed": False, "rc": None, "elapsed_sec": 0.0, "timed_out": False, "cmd": []},
            mutants_records=[],
            skipped_nodes=0,
            invalid_count=0,
            stale_accepted=[],
            unnecessary_accepted=[],
            exit_code=2,
            verdict="ERROR",
            reason=exc.code,
        )
        if ns.json_out:
            out_p = Path(ns.json_out)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_bytes((json.dumps(err_report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print(f"DIFF_AST_MUTATE ERROR mode={'list' if ns.list_only else 'run'} total=0 caught=0 timeout=0 survived=0 accepted=0 invalid=0 reason={exc.code}")
        return 2

    if ns.json_out:
        out_p = Path(ns.json_out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    s = report["summary"]
    label = "PASS" if rc == 0 else ("FAIL" if rc == 1 else "ERROR")
    print(
        f"DIFF_AST_MUTATE {label} mode={report['mode']} total={s['total']} "
        f"caught={s['caught']} timeout={s['caught_timeout']} survived={s['survived']} "
        f"accepted={s['accepted']} invalid={s['invalid']} reason={s['reason']}"
    )
    if s["survived"] > 0:
        for m in report["mutants"]:
            if m["status"] == "SURVIVED":
                print(
                    f"SURVIVED {m['id']} {m['display_id']} {m['file']}:{m['lineno']} "
                    f"[{m['op']}] {m['original']!r} -> {m['mutated']!r}"
                )
    if s["accepted"] > 0:
        for m in report["mutants"]:
            if m["status"] == "ACCEPTED":
                print(
                    f"ACCEPTED {m['id']} {m['display_id']} {m['file']}:{m['lineno']} "
                    f"batch={m['accept_batch']} reason={m['accept_reason']}"
                )
    if report["stale_accepted"]:
        print("STALE_ACCEPTED " + " ".join(report["stale_accepted"]))
    if report.get("out_of_scope_accepted"):
        print("OUT_OF_SCOPE_ACCEPTED " + " ".join(report["out_of_scope_accepted"]))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
