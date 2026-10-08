#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/gate_runner.py

Canonical local gate runner for Executor batches (B-107 canonical tooling).

Replaces per-batch hand-written gate capture and EXIT_CODE read-back scripts.

  python scripts/gate_runner.py run --task-id <T> --stage PRECOMMIT|STAGED|POSTCOMMIT
  python scripts/gate_runner.py verify --task-id <T> --stage PRECOMMIT|STAGED|POSTCOMMIT

run:    validates the current task prompt and the .git/<T>-local-gates.txt artifact path,
        then executes the fixed gate sequence of the stage in order (no shell), appending
        to the log for every gate a header, the complete stdout/stderr (each line prefixed
        with "> "), and "EXIT_CODE: <n>" written only after the process has ended.
        The first non-zero gate stops the run and writes a FAILED marker; a fully passing
        run ends with a COMPLETE marker. Earlier runs are never modified or removed.
        Each gate runs through scripts/bounded_process.py: it starts in its own process
        group, its output goes to an anonymous temporary file instead of a pipe, and on
        timeout the whole gate process tree is terminated; the gate is then recorded as
        "TREE_KILL: <status>" followed by "EXIT_CODE: TIMEOUT".
verify: re-reads the log and passes only if the latest run of the stage contains every
        gate header in order, each followed by EXIT_CODE: 0, and the COMPLETE marker.

Exit codes: run returns 0 on success, the failing gate's exit code (or 1) otherwise;
verify returns 0 or 1; usage errors return 2. Apart from the log, only anonymous
temporary files that the operating system removes on close are created; nothing is
deleted.
"""

import argparse
import os
import sys

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from scripts.bounded_process import run_bounded  # noqa: E402
from scripts.governance_preflight import (  # noqa: E402
    is_safe_task_id,
    verify_current_task_prompt,
    verify_task_artifact_path,
)

PY = "python"
STAGES = {
    "PRECOMMIT": [
        [PY, "scripts/execution_record.py", "verify", "--as-if-committed"],
        [PY, "scripts/fingerprint.py", "--verify"],
        [PY, "scripts/check_consistency.py", "--as-if-committed"],
        [PY, "scripts/verify_all.py"],
        ["git", "diff", "--check"],
    ],
    "STAGED": [
        [PY, "scripts/secret_scan.py", "--staged"],
    ],
    "POSTCOMMIT": [
        [PY, "scripts/execution_record.py", "verify"],
        [PY, "scripts/verify_all.py"],
        ["git", "diff", "--check"],
    ],
}
GATE_TIMEOUT_SECONDS = 1800
OUTPUT_PREFIX = "> "


def display(cmd):
    return " ".join(cmd)


def run_header(stage, run_no):
    return f"=== {stage} RUN {run_no} START ==="


def gate_header(stage, run_no, idx, cmd):
    return f"=== {stage} RUN {run_no} GATE {idx}: {display(cmd)} ==="


def complete_marker(stage, run_no):
    return f"=== {stage} RUN {run_no} COMPLETE ==="


def failed_marker(stage, run_no, idx):
    return f"=== {stage} RUN {run_no} FAILED AT GATE {idx} ==="


def read_log_lines(log_path):
    if not os.path.exists(log_path):
        return []
    with open(log_path, "rb") as handle:
        return handle.read().decode("utf-8", errors="replace").split("\n")


def next_run_number(lines, stage):
    prefix = f"=== {stage} RUN "
    count = 0
    for line in lines:
        if line.startswith(prefix) and line.endswith(" START ==="):
            count += 1
    return count + 1


def append_lines(log_path, lines):
    data = ("\n".join(lines) + "\n").encode("utf-8")
    with open(log_path, "ab") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def resolve_command(cmd):
    if cmd and cmd[0] == PY:
        return [sys.executable] + cmd[1:]
    return list(cmd)


def run_stage(root, stage, gates, log_path, timeout=GATE_TIMEOUT_SECONDS):
    lines = read_log_lines(log_path)
    run_no = next_run_number(lines, stage)
    append_lines(log_path, [run_header(stage, run_no)])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    for idx, cmd in enumerate(gates, 1):
        append_lines(log_path, [gate_header(stage, run_no, idx, cmd)])
        res = run_bounded(resolve_command(cmd), cwd=root, timeout=timeout, env=env, merge_stderr=True)
        output = res.stdout.decode("utf-8", errors="replace")
        trailer = []
        if res.launch_error is not None:
            code = 1
            code_text = "LAUNCH_FAILED"
        elif res.timed_out:
            code = 1
            code_text = "TIMEOUT"
            trailer = [f"TREE_KILL: {res.kill_status}"]
        else:
            code = res.returncode
            code_text = str(code)
        body = [OUTPUT_PREFIX + l for l in output.replace("\r\n", "\n").rstrip("\n").split("\n")] if output else []
        append_lines(log_path, body + trailer + [f"EXIT_CODE: {code_text}"])
        suffix = f" TREE_KILL {res.kill_status}" if trailer else ""
        print(f"{stage} RUN {run_no} GATE {idx}: EXIT_CODE {code_text}{suffix}")
        if code != 0:
            append_lines(log_path, [failed_marker(stage, run_no, idx)])
            return code if code > 0 else 1
    append_lines(log_path, [complete_marker(stage, run_no)])
    return 0


def verify_stage(lines, stage, gates):
    starts = [i for i, l in enumerate(lines) if l.startswith(f"=== {stage} RUN ") and l.endswith(" START ===")]
    if not starts:
        return False, "NO_RUN"
    start = starts[-1]
    run_no = len(starts)
    if lines[start] != run_header(stage, run_no):
        return False, "RUN_HEADER_MISMATCH"
    segment = lines[start + 1:]
    end_markers = {complete_marker(stage, run_no)} | {failed_marker(stage, run_no, i) for i in range(1, len(gates) + 1)}
    for pos, line in enumerate(segment):
        if line in end_markers:
            segment = segment[:pos + 1]
            break
    pos = 0
    for idx, cmd in enumerate(gates, 1):
        header = gate_header(stage, run_no, idx, cmd)
        try:
            pos = segment.index(header, pos) + 1
        except ValueError:
            return False, f"GATE_{idx}_MISSING"
        exit_line = None
        while pos < len(segment):
            line = segment[pos]
            pos += 1
            if line.startswith("EXIT_CODE: "):
                exit_line = line
                break
            if line.startswith("=== "):
                break
        if exit_line != "EXIT_CODE: 0":
            return False, f"GATE_{idx}_NOT_ZERO"
    if complete_marker(stage, run_no) not in segment[pos:]:
        return False, "NOT_COMPLETE"
    return True, f"RUN_{run_no}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Canonical local gate runner (B-107 canonical tooling).")
    parser.add_argument("action", choices=["run", "verify"])
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    parser.add_argument("--repo-root", default=".")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if not is_safe_task_id(args.task_id):
        print("S1 USAGE_INVALID_TASK_ID")
        return 2
    root = os.path.abspath(args.repo_root)
    ok_prompt, err_prompt, _, _ = verify_current_task_prompt(root, args.task_id)
    if not ok_prompt:
        print(err_prompt)
        return 1
    rel_log = f".git/{args.task_id}-local-gates.txt"
    ok_art, err_art = verify_task_artifact_path(root, args.task_id, rel_log)
    if not ok_art:
        print(err_art)
        return 1
    log_path = os.path.join(root, ".git", f"{args.task_id}-local-gates.txt")
    gates = STAGES[args.stage]
    if args.action == "run":
        code = run_stage(root, args.stage, gates, log_path)
        print(f"GATE_RUNNER {'PASS' if code == 0 else 'FAIL'} stage={args.stage}")
        return code
    ok, detail = verify_stage(read_log_lines(log_path), args.stage, gates)
    if ok:
        print(f"GATE_VERIFY PASS stage={args.stage} {detail}")
        return 0
    print(f"S1 GATE_COMPLETION_UNPROVEN stage={args.stage} {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
