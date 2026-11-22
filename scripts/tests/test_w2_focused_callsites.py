# -*- coding: utf-8 -*-
"""Second-opinion proposal (D9-2): lock the three call sites of the w2_focused binding.

Single-point mutations that survived the six required test files at the reviewed bytes:
prompt_builder.build no longer adds the flag; prompt_builder.check no longer verifies the binding;
batch_runner.Batch.__init__ no longer verifies the binding. Each test below fails on exactly one of them.
"""
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import batch_runner as br  # noqa: E402
import prompt_builder as pb  # noqa: E402
from test_prompt_builder import TASK, _Result, _code, _definition, _git, repo  # noqa: E402,F401

FOCUSED = {"pytest_args": ["-q", "-rs", "scripts/tests/test_x.py"], "limit_sec": 900}
DECLARING = b"PRODUCTION_STEPS = ('preflight', 'setup', 'apply')\nSPEC_FLAGS = ('w2_focused',)\n"


def _declaring_base(root):
    (Path(root) / "scripts" / "batch_runner.py").write_bytes(DECLARING)
    _git(root, "commit", "-qam", "declare")
    return _git(root, "rev-parse", "HEAD").stdout.decode().strip()


def _build_spec(tmp_path, root, base, name):
    out = tmp_path / name
    pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base, focused=FOCUSED), "--out-dir", str(out)])
    path = out / (TASK + "-prompt.txt")
    spec = json.loads(br.extract_block(br.prompt_lines(path.read_bytes()), "BATCH_SPEC_JSON"))
    return path, spec


def test_build_adds_the_flag_only_for_a_declaring_base(tmp_path, repo):
    root, older = repo
    _, spec = _build_spec(tmp_path, root, older, "older")
    assert "w2_focused" not in spec
    _, spec = _build_spec(tmp_path, root, _declaring_base(root), "declaring")
    assert spec["w2_focused"] is False


def test_check_refuses_a_prompt_whose_flag_disagrees_with_its_base(tmp_path, repo):
    root, older = repo
    path, _ = _build_spec(tmp_path, root, older, "older")
    data = path.read_bytes()
    marker = b'"focused": {'
    assert data.count(marker) == 1
    path.write_bytes(data.replace(marker, b'"w2_focused": false,\n "focused": {'))
    assert _code(pb.check, root, str(path), lambda *a, **k: _Result(0)) == "CHECK_W2_FOCUSED_SPEC_MISMATCH"


def test_real_batch_constructor_checks_the_flag_binding(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "FIXTURE-prompt.txt").write_bytes(b"fixture")
    spec = {"kind": "production", "base_oid": "a" * 40, "focused": FOCUSED, "authors": {"scripts/tool.py": {}}}
    monkeypatch.setattr(br, "load_spec", lambda *args: spec)
    monkeypatch.setattr(br, "base_supports_native_preview", lambda *args: False)
    monkeypatch.setattr(br, "base_supports_w2_focused", lambda *args: True)
    with pytest.raises(br.Halt, match="^W2_FOCUSED_SPEC_MISMATCH$"):
        br.Batch(str(tmp_path), "FIXTURE")
    spec["w2_focused"] = False
    assert br.Batch(str(tmp_path), "FIXTURE").spec["w2_focused"] is False
