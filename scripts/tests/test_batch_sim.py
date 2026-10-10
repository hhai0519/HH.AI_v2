# -*- coding: utf-8 -*-
"""
scripts/tests/test_batch_sim.py

Controls for scripts/batch_sim.py and scripts/sim_windows_emulation.py (B-115 slice 2): isolation of the work
directory, step order, fail-closed result checks, negatives that must stop at the documented step, the CI
stand-in confined to push inside the work clone, fixed output, and the Windows behaviour emulation.
All fixtures are written as bytes (exact LF), never through text-mode writes.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import batch_runner as br  # noqa: E402
import batch_sim as bs  # noqa: E402

BASE = "a" * 40
HEAD = "b" * 40
CAND = "c" * 40
TASK = "SIM-UNIT-261010"
AUTHORED = {"docs/A.md": b"alpha\n", "scripts/tool.py": b"print(1)\n"}


def _w(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _block(name, body):
    return "<<<BEGIN " + name + ">>>\n" + body + "\n<<<END " + name + ">>>\n"


def _prompt(tmp_path, task=TASK, kind="production", start=None, name=None):
    if kind == "production":
        spec = {"schema_version": 1, "task_id": task, "kind": "production", "base_oid": BASE,
                "branch": "batch/sim-unit-261010", "start": start or {"mode": "clean"},
                "authors": {p: {"source": {"kind": "base"}, "sha256": hashlib.sha256(b).hexdigest()}
                            for p, b in AUTHORED.items()}, "ops": []}
        plan = {"task_id": task, "base_oid": BASE, "allowed_paths": sorted(list(AUTHORED) + list(br.GENERATED))}
        text = "head\n" + _block("BATCH_SPEC_JSON", json.dumps(spec)) + _block("PLAN_JSON", json.dumps(plan))
    else:
        spec = {"schema_version": 1, "task_id": task, "kind": "promotion", "base_oid": BASE,
                "candidate_oid": CAND, "candidate_branch": "batch/sim-unit-261010"}
        text = "head\n" + _block("BATCH_SPEC_JSON", json.dumps(spec))
    path = tmp_path / "prompts" / ((name or task) + "-prompt.txt")
    _w(path, text)
    return str(path)


class Fake:
    """Scripted stand-in for every command the simulator runs; records calls and checks the CI stand-in."""

    def __init__(self, tmp_path, steps=None, **over):
        self.tmp = tmp_path
        self.steps = steps or {}
        self.calls = []
        self.stub_seen = {}
        self.state = dict(head=HEAD, parent=BASE, changed=sorted(list(AUTHORED) + list(br.GENERATED)),
                          blobs=dict(AUTHORED), remote=HEAD, cc=0, er=0, status="", main=None, auth=False,
                          main_after_step=None,
                          source_refs=["refs/heads/main " + BASE], wrong_location=None, skip_flag_stuck=False)
        self.source_reads = 0
        self.state.update(over)

    def __call__(self, args, cwd, env, timeout, merge=True):
        args = list(args)
        self.calls.append((args, cwd, dict(env)))
        if args[0] == "git":
            n = len(bs.SIM_IDENTITY)
            a = args[1 + n:] if tuple(args[1:1 + n]) == bs.SIM_IDENTITY else args[1:]
            return self.git(a, cwd)
        script = args[1]
        if script == "scripts/batch_runner.py":
            task, step = args[3], args[4]
            vp = Path(cwd) / "scripts" / "verification_primitives.py"
            self.stub_seen[step] = vp.read_bytes() == bs.CI_STUB.encode("utf-8")
            rc, text = self.steps.get((task, step), (0, "STEP_PASS " + step))
            if step == "promote" and rc == 0:
                self.state["main"] = CAND
                if self.state["auth"]:
                    _w(Path(cwd) / bs.AUTH_FILE, b"{}")
            if self.state["main_after_step"] and self.state["main_after_step"][0] == step:
                self.state["main"] = self.state["main_after_step"][1]
            return rc, text.encode("utf-8")
        if script == "scripts/check_consistency.py":
            return self.state["cc"], b""
        if script == "scripts/execution_record.py":
            return self.state["er"], b""
        return 0, b""

    def git(self, a, cwd):
        s = self.state
        wd = Path(cwd).parent if Path(cwd).name == "work" else Path(cwd)
        if a[0] == "-C" and a[2] == "for-each-ref" and Path(a[1]).name == "src":
            refs = s["source_refs"]
            self.source_reads += 1
            text = refs[min(self.source_reads, len(refs)) - 1] if isinstance(refs, list) else refs
            return 0, text.encode()
        if a[:2] == ["rev-parse", "--show-toplevel"]:
            return 0, (str(wd / ("elsewhere" if s["wrong_location"] == "top" else "work")) + "\n").encode()
        if a[:2] == ["rev-parse", "--absolute-git-dir"]:
            return 0, (str(wd / "work" / (".git2" if s["wrong_location"] == "gitdir" else ".git")) + "\n").encode()
        if a[0] == "-C" and a[2:4] == ["rev-parse", "--absolute-git-dir"]:
            return 0, (a[1] + ("x" if s["wrong_location"] == "origin" else "") + "\n").encode()
        if a[:2] == ["remote", "get-url"]:
            push = "--push" in a
            bad = s["wrong_location"] == ("push" if push else "fetch")
            return 0, (str(wd / ("other.git" if bad else "origin.git")) + "\n").encode()
        if a[:2] == ["ls-files", "-v"]:
            return 0, (b"S " if s["skip_flag_stuck"] else b"H ") + a[-1].encode() + b"\n"
        if a[0] == "clone":
            target = Path(a[-1])
            target.mkdir(parents=True)
            if target.name == "work":
                _w(target / "scripts" / "verification_primitives.py", b"REAL\n")
                _w(target / "scripts" / "batch_runner.py", b"# runner\n")
                for p, b in AUTHORED.items():
                    _w(target / p, b)
                (target / ".git").mkdir()
            return 0, b""
        if a[0] == "-C" and "for-each-ref" in a:
            return 0, b"refs/heads/main\nrefs/heads/other\n"
        if a[0] == "-C" and a[2] == "rev-parse" and a[3] == "refs/heads/main":
            return 0, (s["main"] + "\n").encode()
        if a[0] == "-C" and a[2:4] == ["update-ref", "refs/heads/main"]:
            s["main"] = a[4]
            return 0, b""
        if a[:2] == ["rev-parse", "HEAD"]:
            return 0, (s["head"] + "\n").encode()
        if a[:2] == ["rev-parse", "HEAD^"]:
            return 0, (s["parent"] + "\n").encode()
        if a[0] == "rev-parse" and a[1].endswith("^"):
            return 0, ("d" * 40 + "\n").encode()
        if a[:2] == ["diff", "--name-only"]:
            return 0, "\n".join(s["changed"]).encode()
        if a[0] == "ls-remote":
            return 0, (s["remote"] + "\trefs/heads/x\n").encode()
        if a[:2] == ["status", "--porcelain"]:
            return 0, s["status"].encode()
        if a[:2] == ["cat-file", "blob"]:
            path = a[2].split(":", 1)[1]
            return (0, s["blobs"][path]) if path in s["blobs"] else (128, b"")
        if a[0] == "checkout":
            _w(Path(cwd) / "scripts" / "verification_primitives.py", b"REAL\n")
        return 0, b""

    def runner_steps(self):
        return [c[0][4] for c in self.calls if len(c[0]) > 4 and c[0][1] == "scripts/batch_runner.py"]


def _sim(tmp_path, fake, locale="utf8"):
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    lines = []
    return bs.Sim(str(src), str(tmp_path / "wd"), locale, run=fake, out=lines.append), lines


def _code(fn, *args, **kw):
    with pytest.raises(bs.SimError) as exc:
        fn(*args, **kw)
    return str(exc.value)


# --- isolation ---------------------------------------------------------------------------------

def test_workdir_must_be_new_or_empty_and_outside_the_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    assert _code(bs.check_workdir, str(src), str(src)) == "WORKDIR_OVERLAPS_SOURCE"
    assert _code(bs.check_workdir, str(src / "inner"), str(src)) == "WORKDIR_OVERLAPS_SOURCE"
    assert _code(bs.check_workdir, str(tmp_path), str(src)) == "WORKDIR_OVERLAPS_SOURCE"
    busy = tmp_path / "busy"
    _w(busy / "x", b"x")
    assert _code(bs.check_workdir, str(busy), str(src)) == "WORKDIR_NOT_EMPTY"
    assert bs.check_workdir(str(tmp_path / "new"), str(src)).is_dir()


def test_origin_keeps_only_main_at_base_and_never_touches_the_source(tmp_path):
    fake = Fake(tmp_path)
    sim, _ = _sim(tmp_path, fake)
    sim.production(_prompt(tmp_path))
    git_calls = [c[0] for c in fake.calls if c[0][0] == "git"]
    assert any("update-ref" in c and "-d" in c and "refs/heads/other" in c for c in git_calls)
    assert any(c[-2:] == ["refs/heads/main", BASE] for c in git_calls)
    src = str((tmp_path / "src").resolve())
    assert all(cwd != src for _, cwd, _ in fake.calls), "no command runs inside the source repository"


# --- production --------------------------------------------------------------------------------

def test_production_runs_steps_in_order_and_ci_stand_in_only_for_push(tmp_path):
    fake = Fake(tmp_path)
    sim, lines = _sim(tmp_path, fake)
    sim.production(_prompt(tmp_path))
    assert fake.runner_steps() == list(bs.PRODUCTION_STEPS) + ["push"]
    assert fake.stub_seen["push"] is True
    assert not any(v for k, v in fake.stub_seen.items() if k != "push")
    vp = tmp_path / "wd" / "work" / "scripts" / "verification_primitives.py"
    assert vp.read_bytes() == b"REAL\n", "the stand-in is removed after push"
    assert lines == ["BATCH_SIM STEP " + s + " rc=0" for s in list(bs.PRODUCTION_STEPS) + ["push"]]


def test_posix_locale_proxy_reaches_every_command(tmp_path):
    fake = Fake(tmp_path)
    sim, _ = _sim(tmp_path, fake, locale="posix")
    sim.production(_prompt(tmp_path))
    assert all(env.get("LC_ALL") == "POSIX" and env.get("PYTHONUTF8") == "0" for _, _, env in fake.calls)


def test_step_failure_stops_with_fixed_code_and_reports_only_the_s1_code(tmp_path):
    fake = Fake(tmp_path, steps={(TASK, "focused"): (1, "noise secret-looking text\nS1 FOCUSED_NONZERO | step focused\n")})
    sim, lines = _sim(tmp_path, fake)
    assert _code(sim.production, _prompt(tmp_path)) == "STEP_FAILED_FOCUSED_FOCUSED_NONZERO"
    assert fake.runner_steps()[-1] == "focused"
    assert lines[-1] == "BATCH_SIM S1 FOCUSED_NONZERO"
    assert not any("secret" in l for l in lines)


@pytest.mark.parametrize("over,code", [
    ({"parent": "e" * 40}, "RESULT_PARENT_MISMATCH"),
    ({"changed": ["docs/A.md"]}, "RESULT_SCOPE_MISMATCH"),
    ({"blobs": {"docs/A.md": b"alpha\r\n", "scripts/tool.py": b"print(1)\n"}}, "RESULT_AUTHOR_HASH_MISMATCH"),
    ({"blobs": {"docs/A.md": b"alpha\n"}}, "RESULT_AUTHOR_MISSING"),
    ({"remote": "f" * 40}, "RESULT_REMOTE_MISMATCH"),
    ({"cc": 1}, "RESULT_CONSISTENCY_FAILED"),
    ({"er": 2}, "RESULT_EXECUTION_RECORD_FAILED"),
    ({"status": " M docs/A.md"}, "RESULT_WORKTREE_DIRTY"),
])
def test_result_checks_fail_closed(tmp_path, over, code):
    sim, _ = _sim(tmp_path, Fake(tmp_path, **over))
    assert _code(sim.production, _prompt(tmp_path)) == code


def test_resume_rebuilds_the_stop_state_before_the_adopt_start(tmp_path):
    adopt = {"mode": "adopt", "start_branch": "batch/stopped-261010", "adopt_hashes": {"docs/A.md": "0" * 64}}
    prompt = _prompt(tmp_path, start=adopt)
    stopped = _prompt(tmp_path, task="STOPPED-261010")
    data = json.loads(br.extract_block(br.prompt_lines(Path(stopped).read_bytes()), "BATCH_SPEC_JSON"))
    data["branch"] = "batch/stopped-261010"
    _w(stopped, "head\n" + _block("BATCH_SPEC_JSON", json.dumps(data)) + _block("PLAN_JSON", "{}"))
    fake = Fake(tmp_path)
    sim, _ = _sim(tmp_path, fake)
    sim.production(prompt, resume_prompt=stopped)
    tasks = [c[0][3] for c in fake.calls if c[0][1] == "scripts/batch_runner.py"]
    assert tasks[:4] == ["STOPPED-261010"] * 4 and fake.runner_steps()[:4] == list(bs.RESUME_STEPS)
    assert tasks[4:] == [TASK] * (len(bs.PRODUCTION_STEPS) + 1)


def test_resume_must_match_the_adopt_start(tmp_path):
    sim, _ = _sim(tmp_path, Fake(tmp_path))
    assert _code(sim.production, _prompt(tmp_path), resume_prompt=_prompt(tmp_path, task="X-261010")) == "RESUME_MISMATCH"
    adopt = {"mode": "adopt", "start_branch": "batch/elsewhere-261010", "adopt_hashes": {"docs/A.md": "0" * 64}}
    sim2, _ = _sim(tmp_path / "two", Fake(tmp_path / "two"))
    assert _code(sim2.production, _prompt(tmp_path, start=adopt)) == "RESUME_MISMATCH"


# --- negatives ---------------------------------------------------------------------------------

def test_production_negative_passes_only_on_the_documented_stop(tmp_path):
    ok = Fake(tmp_path, steps={(TASK, "focused"): (1, "S1 CONTROL_BINDING_DRIFT | step focused")}, head=BASE)
    sim, _ = _sim(tmp_path, ok)
    sim.production(_prompt(tmp_path), negative="runner")
    runner = tmp_path / "wd" / "work" / "scripts" / "batch_runner.py"
    assert runner.read_bytes().endswith(b"# injected by batch_sim\n")
    assert fake_steps(ok) == list(bs.RESUME_STEPS) + ["focused"]


def fake_steps(fake):
    return fake.runner_steps()


@pytest.mark.parametrize("steps,over,code", [
    ({}, {"head": BASE}, "NEGATIVE_NOT_STOPPED_FOCUSED_AUTHOR_DRIFT"),                       # fault not caught
    ({(TASK, "focused"): (1, "S1 OTHER | step focused")}, {"head": BASE}, "NEGATIVE_NOT_STOPPED_FOCUSED_AUTHOR_DRIFT"),
    ({(TASK, "focused"): (1, "S1 FOCUSED_AUTHOR_DRIFT | step focused")}, {}, "NEGATIVE_COMMITTED"),
])
def test_production_negative_fails_closed(tmp_path, steps, over, code):
    sim, _ = _sim(tmp_path, Fake(tmp_path, steps=steps, **over))
    assert _code(sim.production, _prompt(tmp_path), negative="author") == code


def test_negative_stopping_too_early_is_a_failure(tmp_path):
    adopt = {"mode": "adopt", "start_branch": "batch/sim-unit-261010", "adopt_hashes": {"docs/A.md": "0" * 64}}
    stopped = _prompt(tmp_path, task="STOPPED-261010")
    fake = Fake(tmp_path, steps={(TASK, "preflight"): (1, "S1 X | step preflight")}, head=BASE)
    sim, _ = _sim(tmp_path, fake)
    assert _code(sim.production, _prompt(tmp_path, start=adopt), resume_prompt=stopped,
                 negative="adopt") == "NEGATIVE_STOPPED_EARLY_PREFLIGHT"


# --- promotion ---------------------------------------------------------------------------------

def test_promotion_positive_requires_main_at_candidate_and_consumed_authorization(tmp_path):
    fake = Fake(tmp_path)
    sim, _ = _sim(tmp_path, fake)
    sim.promotion(_prompt(tmp_path, kind="promotion"))
    assert fake.runner_steps() == list(bs.PROMOTION_STEPS)
    assert all(fake.stub_seen.values()), "the CI stand-in covers every promotion step"
    vp = tmp_path / "wd" / "work" / "scripts" / "verification_primitives.py"
    assert vp.read_bytes() == b"REAL\n", "and is removed afterwards"
    sim2, _ = _sim(tmp_path / "b", Fake(tmp_path / "b", main_after_step=("postmain", BASE)))
    assert _code(sim2.promotion, _prompt(tmp_path, kind="promotion")) == "RESULT_MAIN_MISMATCH"
    sim3, _ = _sim(tmp_path / "c", Fake(tmp_path / "c", auth=True))
    assert _code(sim3.promotion, _prompt(tmp_path, kind="promotion")) == "RESULT_AUTH_NOT_CONSUMED"


@pytest.mark.parametrize("negative", sorted(bs.PROMOTION_NEGATIVES))
def test_promotion_negatives_require_main_exactly_unchanged(tmp_path, negative):
    step, code = bs.PROMOTION_NEGATIVES[negative]
    stop = {(TASK, step): (1, "S1 " + code + " | step " + step)}
    fake = Fake(tmp_path, steps=stop)
    sim, _ = _sim(tmp_path, fake)
    sim.promotion(_prompt(tmp_path, kind="promotion"), negative=negative)
    assert fake.runner_steps()[-1] == step
    assert fake.state["main"] == ("d" * 40 if negative == "drift" else BASE)
    vp = tmp_path / "wd" / "work" / "scripts" / "verification_primitives.py"
    assert vp.read_bytes() == b"REAL\n", "the CI stand-in is removed after a negative too"
    for other in (CAND, "e" * 40):                   # promoted, or moved to an unrelated third SHA
        moved = Fake(tmp_path / other[:1], steps=stop, main_after_step=(step, other))
        sim2, _ = _sim(tmp_path / other[:1], moved)
        assert _code(sim2.promotion, _prompt(tmp_path, kind="promotion"), negative=negative) == "NEGATIVE_MAIN_CHANGED"


def test_prompt_kind_and_name_are_checked(tmp_path):
    sim, _ = _sim(tmp_path, Fake(tmp_path))
    assert _code(sim.promotion, _prompt(tmp_path)) == "PROMPT_KIND_MISMATCH"
    bad = tmp_path / "x.txt"
    _w(bad, "x")
    assert _code(bs.read_prompt, str(bad)) == "PROMPT_NAME_INVALID"
    assert _code(bs.read_prompt, _prompt(tmp_path, name="OTHER-261010")) == "PROMPT_TASK_MISMATCH"


# --- command execution and CLI -------------------------------------------------------------------

def test_default_run_never_raises_and_reports_timeout_and_launch_failure(tmp_path):
    rc, _ = bs.default_run([sys.executable, "-c", "import time; time.sleep(5)"], str(tmp_path), dict(os.environ), 0.5)
    assert rc == 124
    rc, _ = bs.default_run([str(tmp_path / "missing-exe")], str(tmp_path), dict(os.environ), 5)
    assert rc == 127
    rc, out = bs.default_run([sys.executable, "-c", "import sys; sys.stderr.write('e'); print('o')"],
                             str(tmp_path), dict(os.environ), 30, False)
    assert rc == 0 and out.strip() == b"o", "merge=False keeps exact stdout bytes"


def test_cli_prints_only_fixed_result_lines(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    assert bs.main(["production", "--source", str(src), "--prompt", str(tmp_path / "x.txt"),
                    "--workdir", str(src / "w")]) == 1
    assert capsys.readouterr().out.strip() == "BATCH_SIM FAIL WORKDIR_OVERLAPS_SOURCE"


def test_winemu_prints_only_a_totals_line(tmp_path, capsys):
    def fake(args, cwd, env, timeout, merge):
        assert "sim_windows_emulation" in args and env["PYTHONPATH"].split(os.pathsep)[0].endswith("scripts")
        return 1, b"FAILED t.py::x - AssertionError: private text\n== 1 failed, 2 passed in 0.10s ==\n"
    with pytest.raises(bs.SimError):
        bs.winemu(str(tmp_path), ["t.py"], run=fake)
    assert capsys.readouterr().out.strip() == "BATCH_SIM WINEMU 1 failed, 2 passed in 0.10s"
    bs.winemu(str(tmp_path), ["t.py"], run=lambda *a: (0, b"FAILED secret 1 passed in 2s\n"))
    assert capsys.readouterr().out.strip() == "BATCH_SIM WINEMU (summary withheld)"


# --- Windows behaviour emulation -------------------------------------------------------------------

def test_windows_emulation_translates_newlines_and_denies_symlinks(tmp_path):
    probe = tmp_path / "test_probe.py"
    _w(probe, (
        "import pathlib, pytest\n"
        "def test_probe(tmp_path):\n"
        "    p = tmp_path / 'a.txt'\n"
        "    p.write" "_text('x\\ny\\n', encoding='utf-8')\n"
        "    assert p.read_bytes() == b'x\\r\\ny\\r\\n'\n"
        "    with open(tmp_path / 'b.txt', " "'w', encoding='utf-8') as fh:\n"
        "        fh.write('z\\n')\n"
        "    assert (tmp_path / 'b.txt').read_bytes() == b'z\\r\\n'\n"
        "    q = tmp_path / 'q.txt'\n"
        "    for nl, want in ((None, b'1\\r\\n'), ('', b'1\\n'), ('\\n', b'1\\n'), ('\\r\\n', b'1\\r\\n')):\n"
        "        q.write" "_text('1\\n', encoding='utf-8', newline=nl)\n"
        "        assert q.read_bytes() == want, nl\n"
        "        with open(q, " "'w', encoding='utf-8', newline=nl) as fh:\n"
        "            fh.write('1\\n')\n"
        "        assert q.read_bytes() == want, nl\n"
        "    (tmp_path / 'c.bin').write_bytes(b'k\\n')\n"
        "    assert (tmp_path / 'c.bin').read_bytes() == b'k\\n'\n"
        "    with pytest.raises(OSError) as exc:\n"
        "        (tmp_path / 'l').symlink_to(p)\n"
        "    assert exc.value.winerror == 1314\n"
    ))
    env = dict(os.environ)
    env["PYTHONPATH"] = SCRIPTS_DIR
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "sim_windows_emulation", "-p", "no:cacheprovider",
                        str(probe)], cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    assert r.returncode == 0, r.stdout.decode("utf-8", "replace")[-400:]


def test_fixtures_never_rely_on_default_newline_translation():
    src = Path(__file__).read_bytes().decode("utf-8")
    assert ".write" + "_text(" not in src
    assert not re.search(r"open\([^)]*,\s*[\"'](w|a|x)t?[\"']", src)


# --- second-opinion fixes (B115-SIM-S2 round 1) ------------------------------------------------------

def _git_real(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd, env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]
    return r.stdout.decode().strip()


def test_real_git_isolation_survives_hostile_environment_and_global_config(tmp_path, monkeypatch):
    # Counterexample from the second opinion: GIT_DIR pointing at the source, and a global push URL / URL rewrite
    # that would send pushes elsewhere. The source must keep every branch and origin must be the simulation's own.
    src = tmp_path / "src"
    src.mkdir()
    _git_real(str(src), "init", "-q", "-b", "main")
    _w(src / "f.txt", b"x\n")
    _git_real(str(src), "add", "f.txt")
    _git_real(str(src), "commit", "-q", "-m", "base")
    _git_real(str(src), "branch", "extra")
    base = _git_real(str(src), "rev-parse", "HEAD")
    before = _git_real(str(src), "for-each-ref", "--format=%(refname) %(objectname)")
    hostile = tmp_path / "hostile-global"
    _w(hostile, "[remote \"origin\"]\n\tpushurl = " + str(tmp_path / "elsewhere.git").replace("\\", "/") + "\n"
       "[url \"" + str(tmp_path / "elsewhere2.git").replace("\\", "/") + "\"]\n\tinsteadOf = " + str(tmp_path).replace("\\", "/") + "\n")
    monkeypatch.setenv("GIT_DIR", str(src / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(src))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile))
    sim = bs.Sim(str(src), str(tmp_path / "wd"), "utf8", out=lambda line: None)
    sim.make_origin(base)                          # includes check_locations
    sim.check_source_unchanged()
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    monkeypatch.delenv("GIT_CONFIG_GLOBAL")
    assert _git_real(str(src), "for-each-ref", "--format=%(refname) %(objectname)") == before
    assert not (tmp_path / "elsewhere.git").exists() and not (tmp_path / "elsewhere2.git").exists()
    assert all(not k.upper().startswith("GIT_") or k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_TERMINAL_PROMPT")
               for k in sim.env)


@pytest.mark.parametrize("where,code", [("top", "ISOLATION_WORKTREE"), ("gitdir", "ISOLATION_GIT_DIR"),
                                        ("origin", "ISOLATION_ORIGIN"), ("fetch", "ISOLATION_REMOTE_URL"),
                                        ("push", "ISOLATION_REMOTE_URL")])
def test_isolation_checks_fail_closed(tmp_path, where, code):
    sim, _ = _sim(tmp_path, Fake(tmp_path, wrong_location=where))
    assert _code(sim.production, _prompt(tmp_path)) == code


def test_source_modification_is_detected(tmp_path):
    fake = Fake(tmp_path, source_refs=["refs/heads/main " + BASE, "refs/heads/main " + HEAD])
    sim, _ = _sim(tmp_path, fake)
    assert _code(sim.production, _prompt(tmp_path)) == "SOURCE_MODIFIED"
    fake2 = Fake(tmp_path / "n", source_refs=["refs/heads/main " + BASE, "refs/heads/main " + HEAD],
                 steps={(TASK, "focused"): (1, "S1 CONTROL_BINDING_DRIFT | step focused")}, head=BASE)
    sim2, _ = _sim(tmp_path / "n", fake2)
    assert _code(sim2.production, _prompt(tmp_path), negative="runner") == "SOURCE_MODIFIED"


def test_ci_stand_in_is_restored_when_push_fails_and_restoration_is_verified(tmp_path):
    fake = Fake(tmp_path, steps={(TASK, "push"): (1, "S1 CANDIDATE_CI_NOT_PASS | step push")})
    sim, _ = _sim(tmp_path, fake)
    assert _code(sim.production, _prompt(tmp_path)) == "STEP_FAILED_PUSH_CANDIDATE_CI_NOT_PASS"
    assert (tmp_path / "wd" / "work" / "scripts" / "verification_primitives.py").read_bytes() == b"REAL\n"
    assert any(c[0][-3:] == ["update-index", "--no-skip-worktree", "scripts/verification_primitives.py"]
               for c in fake.calls)
    stuck = Fake(tmp_path / "s", skip_flag_stuck=True)
    sim2, _ = _sim(tmp_path / "s", stuck)
    assert _code(sim2.production, _prompt(tmp_path)) == "CI_STAND_IN_NOT_RESTORED"


def test_unlisted_s1_text_is_never_echoed(tmp_path):
    fake = Fake(tmp_path, steps={(TASK, "focused"): (1, "S1 SYNTHETIC_PRIVATE_TEXT | step focused")})
    sim, lines = _sim(tmp_path, fake)
    assert _code(sim.production, _prompt(tmp_path)) == "STEP_FAILED_FOCUSED_S1_UNLISTED"
    assert lines[-1] == "BATCH_SIM S1 S1_UNLISTED"
    assert not any("SYNTHETIC" in line or "PRIVATE" in line for line in lines)


@pytest.mark.parametrize("code,expected", [
    ("CONTROL_BINDING_DRIFT", "CONTROL_BINDING_DRIFT"), ("APPLY_SCOPE_MISMATCH", "APPLY_SCOPE_MISMATCH"),
    ("FOCUSED_NONZERO", "FOCUSED_NONZERO"), ("MAIN_PUSH_FAILED_AUTH_FILE_PRESENT", "MAIN_PUSH_FAILED_AUTH_FILE_PRESENT"),
    ("SYNTHETIC_PRIVATE_TEXT", "S1_UNLISTED"), ("FOCUSED_PRIVATE", "S1_UNLISTED"), ("lower case", "S1_UNLISTED"),
    ("A" * 200, "S1_UNLISTED"), ("", "S1_UNLISTED"),
])
def test_s1_vocabulary_comes_only_from_runner_constants(code, expected):
    assert bs.known_s1(code) == expected


TREE_CHILD = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "open(sys.argv[1], 'wb').write(str(g.pid).encode())\n"
    "time.sleep(120)\n"
)


def test_default_run_timeout_terminates_descendants(tmp_path):
    import time
    import bounded_process as bp
    pid_file = tmp_path / "grandchild.pid"
    started = time.monotonic()
    rc, _ = bs.default_run([sys.executable, "-c", TREE_CHILD, str(pid_file)], str(tmp_path), dict(os.environ), 10)
    assert rc == 124 and time.monotonic() - started < 90
    assert pid_file.exists(), "the grandchild started before the timeout"
    pid = int(pid_file.read_bytes())
    deadline = time.monotonic() + 15
    while bp.process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not bp.process_alive(pid), "the whole tree is terminated on timeout"
