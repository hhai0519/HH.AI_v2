#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/batch_sim.py
Auditor-side isolated simulation of a canonical runner batch before delivery (B-115).

It never touches the source repository or any real remote: it bare-clones the source into an empty work
directory, uses that bare clone as "origin", runs the delivered prompt with the canonical scripts/batch_runner.py
step by step, and checks the result mechanically. It never executes a batch for real and is not run by Executors.

Usage:
  python scripts/batch_sim.py production --source <repo> --prompt <file> --workdir <empty dir>
                              [--locale utf8|posix] [--resume-prompt <stopped batch prompt>]
                              [--negative runner|author|adopt] [--git-profile isolated|windows]
  python scripts/batch_sim.py promotion  --source <repo> --prompt <file> --workdir <empty dir>
                              [--locale utf8|posix] [--negative drift|dirty|runner|prompt]
                              [--git-profile isolated|windows]
  python scripts/batch_sim.py winemu     --repo <repo> [--git-profile windows|isolated] -- <pytest arguments>

Production: origin main = the prompt's base_oid; the work clone starts on batch/sim-start (or, with
--resume-prompt, first runs preflight..apply of the stopped batch, rebuilding its stop state for an adopt start).
The steps are exactly the runner's own list for the spec (batch_runner.derive_steps: e24 only when the spec says
so, focused only when it is not null), run in order up to postcommit; push runs with the GitHub CI query replaced by a fixed success stand-in
inside the work clone only (the simulation has no GitHub access). Result checks: parent = base, changed paths =
PLAN_JSON allowed paths, every author file at HEAD has the declared SHA-256 (LF), origin branch = HEAD,
check_consistency and execution_record verify exit 0, clean worktree.
Promotion: origin main = base_oid, origin candidate branch = candidate_oid; steps preflight, verify, promote,
postmain; result: origin main = candidate and the single-use authorization file is consumed.
Negatives inject one fault and require the documented S1 line at the documented step, with nothing committed
(production) or origin main exactly at its expected value (promotion: the injected parent for drift, Base otherwise).

Isolation: the work directory must be new or empty and outside the source; every git command runs without any
inherited GIT_* variable and with an empty global configuration (no system configuration), clones use an empty
template; HOME and XDG_CONFIG_HOME point at the simulation's own empty directories, so a tool or test that drops
GIT_CONFIG_GLOBAL still finds no host ~/.gitconfig or $XDG_CONFIG_HOME/git/config (B-123a); the work tree, git directory and both origin URLs are verified to be the simulation's own paths, and the
source must be unchanged at the end (refs and file metadata, see Trust boundary). Every command runs through bounded_process.run_bounded
(own process group, output to temporary files, whole tree terminated on timeout). S1 codes are printed only when
they belong to the runner's own constant vocabulary; anything else is printed as S1_UNLISTED.
winemu runs pytest with scripts/sim_windows_emulation.py loaded (an emulation, never native Windows evidence), in
the same environment isolation (own temporary HOME/XDG_CONFIG_HOME, no inherited GIT_* variable).

Git profiles (B-123a): "isolated" (production/promotion default) is the behaviour above: GIT_CONFIG_NOSYSTEM=1.
"windows" (winemu default) reproduces the configuration sources of the USER's Git for Windows: a simulation-owned
system file (GIT_CONFIG_SYSTEM, never the host's) with the installer defaults core.autocrlf=true and
core.symlinks=false, the empty isolated global file, and core.symlinks=false in the local config of the work clone
(what a Windows clone writes on a file system without symlink support). Before any step the effective values are
checked, with positive and negative expectations, for three kinds of Git subprocess:
  ambient   the simulation environment unchanged (runner, gates, tests that do not isolate) in the work clone,
            and for winemu in the --repo the tests actually run in (identity checked; its own local values and any
            include/includeIf must not change the profile or bring in a non-simulation file);
  isolated  a tool that sets GIT_CONFIG_NOSYSTEM=1 and GIT_CONFIG_GLOBAL=os.devnull (bundle_after_push,
            s1_full_capture, c9_s1_capture_guard): the system file must NOT apply, only the local config;
  fresh     a new repository created under the ambient environment (test fixtures, git init in a temporary dir).
Every configuration origin visible to the ambient and fresh kinds, including with GIT_CONFIG_GLOBAL removed, must be
a simulation-owned file or the repository's own .git/config (GIT_PROFILE_HOST_LEAK otherwise). The profile changes
configuration only: native Git behaviour (symlink capability probes, case-insensitive paths, file locking) is not
emulated, and a passing run is not native Windows evidence. Only HOME and XDG_CONFIG_HOME move: on a Windows host
USERPROFILE stays as it is (Git for Windows reads HOME), and the interpreter must not depend on a per-user
site-packages directory under the real home (use a virtual environment).

Trust boundary: a simulation runs the repository's own, reviewed code (runner, gates, tests) for a prompt the
auditor wrote; it is not a sandbox for untrusted code. What it does guarantee: Git isolation (above) and a source
integrity check: before and after, every ref (git for-each-ref) and the metadata (type, mode, size, modification
and change time) of every path under the source directory, .git included, read with Python lstat calls only. No git
command runs in the source's working tree, so the check starts no file-system monitor or filter driver configured in
the source; the git commands that read the source are for-each-ref and the --no-local bare clone (the source's
objects are never shared), and anything the source's own git configuration could start from those two is part of
the trusted source. The check detects changes; it does not prevent them. What it does not provide (accepted residual risk for trusted code):
environment isolation beyond GIT_* (other variables, including any credentials present in the auditor's
environment, are inherited by the runner and the tests), network isolation (only the CI query is answered locally;
any other network access by the code under test is not blocked), and file-system isolation outside the work
directory. For bundle_output=true, validates the runner's optional post-push step shape but does not run bundle; it prints
BATCH_SIM POST_PUSH_BUNDLE NOT_TESTED. Native Windows post-push artifact verification remains separate.

Limits (each fails closed): a step fails when it exits non-zero or prints any line that starts with "S1 ", the
stop rule given to the Executor ("S1 NONE" at the start of a line included; a result line such as
"COMMIT <sha> | CI PASS | S1 NONE" does not start with "S1 "). A negative shows that the documented step stops with the documented S1 code and nothing is committed; it does not
show that no code under test ran before the detection point. Resuming a stopped runner-update batch is not
supported (RESUME_RUNNER_UPDATE_UNSUPPORTED); the author negative needs an author file other than the runner
(NEGATIVE_AUTHOR_UNAVAILABLE).

Platform contract (B-115): the simulator and the tools it checks run on CPython 3.10+ on Linux (auditor) and Windows
(USER); every authored file and fixture is UTF-8 with LF only and is written as bytes; "posix" locale runs the runner
under LC_ALL=POSIX, PYTHONUTF8=0 as a non-UTF-8 proxy; a test may skip only for a documented capability gap (no
symlink privilege on Windows, no FIFO outside POSIX). Native Windows evidence is the USER's local run, not this tool.

Output: "BATCH_SIM STEP <name> rc=<n>" per step, the runner's S1 line when one appears (fixed vocabulary), then
exactly one "BATCH_SIM PASS <mode>" or "BATCH_SIM FAIL <CODE>"; exit status 0 only on PASS. File contents and
other runner output are never printed.
"""

import argparse
import ast
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import batch_runner  # noqa: E402 - the runner's own prompt parser is the reference
    import bounded_process  # noqa: E402 - shared bounded-execution primitive (kills the whole process tree)
finally:
    sys.path.pop(0)

PROMOTION_STEPS = ('preflight', 'verify', 'promote', 'postmain')
STEP_TIMEOUT = 3600
GIT_TIMEOUT = 600
START_BRANCH = 'batch/sim-start'
SIM_IDENTITY = ('-c', 'user.name=HH.AI', '-c', 'user.email=sim@example.invalid')
LOCALES = {
    'utf8': {},
    'posix': {'LC_ALL': 'POSIX', 'LANG': 'POSIX', 'PYTHONCOERCECLOCALE': '0', 'PYTHONUTF8': '0'},
}
# Production negatives; the stop step and code depend on the batch's own step list (see production_negative).
PRODUCTION_NEGATIVES = ('adopt', 'author', 'runner')
PROMOTION_NEGATIVES = {
    'drift': ('verify', 'MAIN_DRIFT'),
    'dirty': ('verify', 'DIRTY_WORKTREE'),
    'runner': ('preflight', 'RUNNER_MODIFIED'),
    'prompt': ('verify', 'CONTROL_BINDING_DRIFT'),
}
CI_STUB = ('import json, runpy, sys\n'
           'if sys.argv[1:2] == ["ci-status"]:\n'
           '    def arg(key): return sys.argv[sys.argv.index(key)+1]\n'
           '    sha, branch, event = arg("--head-sha"), arg("--branch"), arg("--event")\n'
           '    jobs = {name: {"status": "completed", "conclusion": "success"} for name in ("verify", "gateway-windows")}\n'
           '    print(json.dumps({"attempts_used": 1, "branch": branch, "command": "ci-status",\n'
           '         "event": event, "head_sha": sha, "jobs": jobs, "repo": arg("--repo"),\n'
           '         "required_jobs": ["verify", "gateway-windows"], "run_attempt": 1,\n'
           '         "run_conclusion": "success", "run_id": 999001 if branch != "main" else 999002,\n'
           '         "run_status": "completed", "status": "PASS", "tool": "verification_primitives",\n'
           '         "version": 1, "workflow_name": arg("--workflow-name")}, sort_keys=True))\n'
           '    sys.exit(0)  # SIMULATION ONLY: synthetic run_id, no GitHub access\n'
           'runpy.run_path(".git/batch-sim-vp-real.py", run_name="__main__")\n')

AUTH_FILE = '.git/hhai-sensitive-push-auth.json'
GIT_PROFILES = ('isolated', 'windows')
# Git for Windows installer defaults at system scope on the USER machine (B-123a; see the TASKBOARD B-123 row).
WINDOWS_SYSTEM_CONFIG = b'[core]\n\tautocrlf = true\n\tsymlinks = false\n'
S1_UNLISTED = 'S1_UNLISTED'


def runner_codes(path=None):
    """Upper-case string constants of scripts/batch_runner.py (with or without a leading '_', which marks a suffix)
    plus its step names in upper case: the only vocabulary an S1 code may be built from."""
    tree = ast.parse(Path(path or batch_runner.__file__).read_bytes().decode('utf-8'))
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and re.match(r'^_?[A-Z][A-Z0-9_]{1,63}$', n.value)}
    steps = {n.value.upper() for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and re.match(r'^[a-z][a-z0-9]{1,15}$', n.value) and n.value in batch_runner.PRODUCTION_STEPS
             + batch_runner.PROMOTION_STEPS}
    return frozenset(consts | steps)


KNOWN_CODES = runner_codes()


def known_s1(code, known=None):
    """A runner constant, or a constant followed by a constant (label + suffix, e.g. APPLY + _SCOPE_MISMATCH,
    MAIN_PUSH_FAILED_ + AUTH_FILE_PRESENT); anything else is reported only as S1_UNLISTED."""
    known = KNOWN_CODES if known is None else known
    if code in known:
        return code
    for head in known:
        rest = code[len(head):]
        if not head.startswith('_') and code.startswith(head) and rest and (rest in known or '_' + rest in known):
            return code
    return S1_UNLISTED
PYTEST_TOTALS = re.compile(r'^\d+ [a-z]+(, \d+ [a-z]+)* in [0-9.]+s( \([0-9:]+\))?$')


def production_steps(spec):
    """Runner's pre-push steps, excluding push and optional post-push bundle.

    A true batch may be rehearsed through its commit/CI stand-in without creating
    an artifact in the real Downloads directory. That post-push step is NOT TESTED.
    """
    steps = batch_runner.derive_steps(spec)
    tail = ['push', 'bundle'] if spec.get('bundle_output') is True else ['push']
    _require(steps[:2] == ['preflight', 'setup'] and 'apply' in steps
             and steps[-len(tail):] == tail and steps.count('push') == 1
             and steps.count('bundle') == (1 if spec.get('bundle_output') is True else 0),
             'STEP_LIST_UNEXPECTED')
    return tuple(steps[:-len(tail)])


def resume_steps(spec):
    """Steps of a stopped batch up to and including apply, as the runner derives them."""
    steps = production_steps(spec)
    return steps[:steps.index('apply') + 1]


def production_negative(spec, negative):
    """(stop step, expected S1 code) for a production fault; the first step after apply checks the injection."""
    if negative == 'adopt':
        return 'setup', 'ADOPT_HASH_MISMATCH'
    steps = production_steps(spec)
    after = steps[steps.index('apply') + 1]
    return after, ('CONTROL_BINDING_DRIFT' if negative == 'runner' else after.upper() + '_AUTHOR_DRIFT')


class SimError(Exception):
    """Fixed failure code; never carries file content."""


def _require(cond, code):
    if not cond:
        raise SimError(code)


def default_run(args, cwd, env, timeout, merge=True):
    """Run a command through bounded_process.run_bounded; return (exit code, output bytes). Never raises.

    The child gets its own process group, stdin is closed and output goes to temporary files, so a descendant
    holding an inherited handle cannot block the caller; on timeout the whole process tree is terminated.
    merge=True folds stderr into the output (step logs); merge=False drops stderr (exact blob bytes).
    A timeout returns 124 (125 if the tree kill was not confirmed), a launch failure 127.
    """
    r = bounded_process.run_bounded(list(args), cwd, timeout, env=env, merge_stderr=merge)
    if r.launch_error is not None:
        return 127, b''
    if r.timed_out:
        return (124 if r.kill_status == bounded_process.KILL_TREE_SIGNALLED else 125), b''
    return (r.returncode if r.returncode is not None else 125), r.stdout


def read_prompt(path):
    """Return (task_id, prompt bytes, spec, plan) using the runner's own parser."""
    name = Path(path).name
    _require(name.endswith('-prompt.txt'), 'PROMPT_NAME_INVALID')
    task = name[:-len('-prompt.txt')]
    _require(batch_runner.TASK_RE.match(task) is not None, 'PROMPT_NAME_INVALID')
    try:
        data = Path(path).read_bytes()
        lines = batch_runner.prompt_lines(data)
        spec = json.loads(batch_runner.extract_block(lines, 'BATCH_SPEC_JSON'))
        plan = json.loads(batch_runner.extract_block(lines, 'PLAN_JSON')) if spec.get('kind') == 'production' else None
    except (OSError, ValueError, batch_runner.Halt):
        raise SimError('PROMPT_UNREADABLE')
    _require(isinstance(spec, dict) and spec.get('task_id') == task, 'PROMPT_TASK_MISMATCH')
    return task, data, spec, plan


def check_workdir(workdir, source):
    """The work directory must be new or empty and must not overlap the source repository."""
    w = Path(workdir).resolve()
    s = Path(source).resolve()
    _require(w != s and s not in w.parents and w not in s.parents, 'WORKDIR_OVERLAPS_SOURCE')
    if w.exists():
        _require(w.is_dir() and not any(w.iterdir()), 'WORKDIR_NOT_EMPTY')
    else:
        w.mkdir(parents=True)
    return w


def isolated_env(root, extra=None, profile='isolated'):
    """Environment for every simulated command: no inherited GIT_* variable (GIT_DIR, GIT_WORK_TREE,
    GIT_CONFIG_*, ...), HOME and XDG_CONFIG_HOME in <root>/home (empty), the empty <root>/isolated-gitconfig as the
    only global configuration, and either no system configuration (isolated) or the simulation-owned Windows
    system file <root>/git-system-windows (windows). Host url rewrites, push URLs, hooksPath and templates never apply.
    """
    _require(profile in GIT_PROFILES, 'GIT_PROFILE_INVALID')
    root = Path(root)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(extra or {})
    home = root / 'home'
    xdg = home / '.config'
    xdg.mkdir(parents=True, exist_ok=True)
    gitconfig = root / 'isolated-gitconfig'
    gitconfig.write_bytes(b'')
    env.update({'HOME': str(home), 'XDG_CONFIG_HOME': str(xdg), 'GIT_CONFIG_GLOBAL': str(gitconfig),
                'GIT_TERMINAL_PROMPT': '0'})
    if profile == 'windows':
        system = root / 'git-system-windows'
        system.write_bytes(WINDOWS_SYSTEM_CONFIG)
        env['GIT_CONFIG_SYSTEM'] = str(system)
    else:
        env['GIT_CONFIG_NOSYSTEM'] = '1'
    return env


def _effective(run, env, cwd, key):
    """(scope, value) of one key as Git resolves it for this environment, or None when unset."""
    rc, out = run(['git', 'config', '--show-scope', '--get', key], cwd, env, GIT_TIMEOUT, False)
    text = out.decode('utf-8', 'replace').strip()
    if rc == 1 or (rc == 0 and not text):
        return None
    parts = text.split('\t')
    _require(rc == 0 and len(parts) == 2, 'GIT_PROFILE_UNREADABLE')
    return parts[0], parts[1]


def _origin_key(origin):
    """Comparable form of a --show-origin value: the repository's own relative .git/config stays as is, any other
    file is resolved and case-normalised (Git for Windows prints forward slashes)."""
    if not origin.startswith('file:') or origin == 'file:.git/config':
        return origin
    return 'file:' + os.path.normcase(os.path.realpath(origin[len('file:'):]))


def _origins(run, env, cwd):
    rc, out = run(['git', 'config', '--show-origin', '--list'], cwd, env, GIT_TIMEOUT, False)
    _require(rc == 0, 'GIT_PROFILE_UNREADABLE')
    return {_origin_key(line.split('\t', 1)[0]) for line in out.decode('utf-8', 'replace').splitlines()
            if line.strip()}


def _same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _check_repo_identity(run, env, repo):
    """The existing repository under test must be a top-level work tree whose git directory is its own .git."""
    for args, want in ((['rev-parse', '--show-toplevel'], repo), (['rev-parse', '--absolute-git-dir'],
                                                                   os.path.join(repo, '.git'))):
        rc, out = run(['git', *args], repo, env, GIT_TIMEOUT, False)
        _require(rc == 0 and _same_path(out.decode('utf-8', 'replace').strip(), want), 'GIT_PROFILE_REPO_IDENTITY')


def check_git_profile(run, env, root, profile, work=None, repo=None):
    """Positive and negative checks of the effective Git configuration for the three kinds of Git subprocess.

    work: the simulation's own work clone (production/promotion), which must also carry the local
          core.symlinks=false of a Windows clone; repo: an existing repository the tests run in (winemu --repo),
          checked read-only (identity, effective values, configuration origins) but never required to carry any
          particular local value. Neither: only the fresh probe. Every check runs before any step or test.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fresh = root / 'probe-fresh'
    rc, _ = run(['git', 'init', '-q', str(fresh)], str(root), env, GIT_TIMEOUT, False)
    _require(rc == 0, 'GIT_PROFILE_UNREADABLE')
    tool_env = dict(env, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    no_global = {k: v for k, v in env.items() if k != 'GIT_CONFIG_GLOBAL'}
    windows = profile == 'windows'
    want_crlf = ('system', 'true') if windows else None
    if repo is not None:
        repo = str(Path(repo).resolve())
        _check_repo_identity(run, env, repo)
    places = ([('FRESH', str(fresh))] + ([('AMBIENT', work)] if work else [])
              + ([('REPO', repo)] if repo is not None else []))
    for kind, cwd in places:
        _require(_effective(run, env, cwd, 'core.autocrlf') == want_crlf, 'GIT_PROFILE_' + kind + '_MISMATCH')
        symlinks = _effective(run, env, cwd, 'core.symlinks')
        if windows:
            _require(symlinks is not None and symlinks[1] == 'false', 'GIT_PROFILE_' + kind + '_MISMATCH')
        else:
            _require(symlinks is None or symlinks[0] == 'local', 'GIT_PROFILE_' + kind + '_MISMATCH')
        # The isolated kind must never see the system file, whatever the profile (NOSYSTEM keeps precedence).
        _require(_effective(run, tool_env, cwd, 'core.autocrlf') is None, 'GIT_PROFILE_ISOLATED_MISMATCH')
        tool_symlinks = _effective(run, tool_env, cwd, 'core.symlinks')
        _require(tool_symlinks is None or tool_symlinks[0] == 'local', 'GIT_PROFILE_ISOLATED_MISMATCH')
        allowed = {'file:.git/config', _origin_key('file:' + env['GIT_CONFIG_GLOBAL'])}
        if windows:
            allowed.add(_origin_key('file:' + env['GIT_CONFIG_SYSTEM']))
        for e in (env, no_global):
            _require(_origins(run, e, cwd) <= allowed, 'GIT_PROFILE_HOST_LEAK')
    if work and windows:
        _require(_effective(run, env, work, 'core.symlinks') == ('local', 'false'), 'GIT_PROFILE_AMBIENT_MISMATCH')
        _require(_effective(run, tool_env, work, 'core.symlinks') == ('local', 'false'),
                 'GIT_PROFILE_ISOLATED_MISMATCH')


class Sim:
    def __init__(self, source, workdir, locale='utf8', run=default_run, out=print, git_profile='isolated'):
        _require(locale in LOCALES, 'LOCALE_INVALID')
        _require(git_profile in GIT_PROFILES, 'GIT_PROFILE_INVALID')
        self.source = str(Path(source).resolve())
        self.workdir = check_workdir(workdir, source)
        self.bare = str(self.workdir / 'origin.git')
        self.work = str(self.workdir / 'work')
        self.downloads = self.workdir / 'downloads'
        self.git_profile = git_profile
        # Git and home isolation; see isolated_env and the module documentation (Isolation, Git profiles).
        self.env = isolated_env(self.workdir, LOCALES[locale], git_profile)
        self.gitconfig = self.workdir / 'isolated-gitconfig'
        self.stubbed = False
        self.run_cmd = run
        self.out = out

    # -- primitives ---------------------------------------------------------------------------------
    def sh(self, args, cwd=None, timeout=GIT_TIMEOUT, merge=True):
        return self.run_cmd(args, cwd or self.work, self.env, timeout, merge)

    def git(self, *args, cwd=None, code='GIT_FAILED'):
        rc, out = self.sh(['git', *SIM_IDENTITY, *args], cwd=cwd, merge=False)
        _require(rc == 0, code)
        return out.decode('utf-8', 'replace').strip()

    def py(self, *args, timeout=GIT_TIMEOUT):
        return self.sh([sys.executable, *args], timeout=timeout)

    # -- set-up -------------------------------------------------------------------------------------
    def source_refs(self):
        """Snapshot of the source: every ref with its object, plus the metadata of every path under the source
        directory (.git included) from Python lstat calls; no git command runs in the source's working tree."""
        refs = self.git('-C', self.source, 'for-each-ref', '--format=%(refname) %(objectname)', cwd=str(self.workdir),
                        code='SOURCE_UNREADABLE')
        entries = []

        def unreadable(err):
            raise SimError('SOURCE_UNREADABLE')
        try:
            for root, dirs, files in os.walk(self.source, onerror=unreadable):
                dirs.sort()
                for name in sorted(dirs) + sorted(files):
                    path = os.path.join(root, name)
                    st = os.lstat(path)
                    entries.append(' '.join((os.path.relpath(path, self.source), oct(st.st_mode), str(st.st_size),
                                             str(st.st_mtime_ns), str(st.st_ctime_ns))))
        except OSError:
            raise SimError('SOURCE_UNREADABLE')
        return refs + '\n--\n' + '\n'.join(entries)

    def check_locations(self):
        """The work clone, its git directory and both origin URLs must be exactly the simulation's own paths."""
        def same(a, b):
            return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
        _require(same(self.git('rev-parse', '--show-toplevel'), self.work), 'ISOLATION_WORKTREE')
        _require(same(self.git('rev-parse', '--absolute-git-dir'), os.path.join(self.work, '.git')), 'ISOLATION_GIT_DIR')
        _require(same(self.git('-C', self.bare, 'rev-parse', '--absolute-git-dir', cwd=str(self.workdir)), self.bare),
                 'ISOLATION_ORIGIN')
        for flag in ((), ('--push',)):
            _require(same(self.git('remote', 'get-url', *flag, 'origin'), self.bare), 'ISOLATION_REMOTE_URL')

    def make_origin(self, main_oid, extra_refs=()):
        self.source_before = self.source_refs()
        self.git('clone', '-q', '--bare', '--no-local', '--template=', self.source, self.bare, cwd=str(self.workdir),
                 code='ORIGIN_CLONE_FAILED')
        heads = self.git('-C', self.bare, 'for-each-ref', '--format=%(refname)', 'refs/heads', cwd=str(self.workdir))
        for ref in heads.split():
            self.git('-C', self.bare, 'update-ref', '-d', ref, cwd=str(self.workdir))
        self.git('-C', self.bare, 'update-ref', 'refs/heads/main', main_oid, cwd=str(self.workdir),
                 code='BASE_NOT_IN_SOURCE')
        for ref, oid in extra_refs:
            self.git('-C', self.bare, 'update-ref', ref, oid, cwd=str(self.workdir), code='CANDIDATE_NOT_IN_SOURCE')
        self.git('-C', self.bare, 'symbolic-ref', 'HEAD', 'refs/heads/main', cwd=str(self.workdir))
        self.git('clone', '-q', '--template=', self.bare, self.work, cwd=str(self.workdir), code='WORK_CLONE_FAILED')
        self.git('config', 'user.name', 'HH.AI')
        self.git('config', 'user.email', 'sim@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        if self.git_profile == 'windows':
            self.git('config', 'core.symlinks', 'false')      # what a Windows clone writes without symlink support
        self.check_locations()
        check_git_profile(self.run_cmd, self.env, self.workdir, self.git_profile, self.work)

    def check_source_unchanged(self):
        _require(self.source_refs() == self.source_before, 'SOURCE_MODIFIED')

    def install_hooks(self):
        rc, _ = self.py('scripts/install_git_hooks.py', '--install')
        _require(rc == 0, 'HOOK_INSTALL_FAILED')

    def intake(self, task, data):
        self.downloads.mkdir(exist_ok=True)
        src = self.downloads / (task + '-prompt.txt')
        src.write_bytes(data)
        rc, _ = self.py('scripts/prompt_intake.py', '--task-id', task, '--source', str(src),
                        '--sha256', hashlib.sha256(data).hexdigest())
        _require(rc == 0, 'INTAKE_FAILED')

    @contextlib.contextmanager
    def ci_stand_in(self):
        """SIMULATION ONLY: answer the GitHub CI query with success inside the work clone; delegate the rest.

        The stand-in exists only inside this block; on every exit (success, S1 stop, exception) the real file and
        the index flag are restored, and the restoration itself is verified (CI_STAND_IN_NOT_RESTORED otherwise).
        """
        vp = Path(self.work) / 'scripts' / 'verification_primitives.py'
        real = vp.read_bytes()
        try:
            self.stubbed = True
            self.git('update-index', '--skip-worktree', 'scripts/verification_primitives.py')
            (Path(self.work) / '.git' / 'batch-sim-vp-real.py').write_bytes(real)
            vp.write_bytes(CI_STUB.encode('utf-8'))
            yield
        finally:
            restored = True
            for args in (('update-index', '--no-skip-worktree', 'scripts/verification_primitives.py'),
                         ('checkout', '-q', '--', 'scripts/verification_primitives.py')):
                rc, _ = self.sh(['git', *SIM_IDENTITY, *args], merge=False)
                restored = restored and rc == 0
            rc, flags = self.sh(['git', 'ls-files', '-v', '--', 'scripts/verification_primitives.py'], merge=False)
            restored = restored and rc == 0 and flags.startswith(b'H ') and vp.read_bytes() == real
            self.stubbed = False
            if not restored:
                raise SimError('CI_STAND_IN_NOT_RESTORED')

    def step(self, task, name):
        """Run one runner step; print its exit code and S1 line (fixed vocabulary); return (rc, S1 code or None)."""
        rc, out = self.py('scripts/batch_runner.py', '--task-id', task, name, timeout=STEP_TIMEOUT)
        self.out('BATCH_SIM STEP ' + name + ' rc=' + str(rc))
        s1 = None
        for line in out.decode('utf-8', 'replace').splitlines():
            if line.startswith('S1 '):
                s1 = known_s1((line.split(' | ')[0].split()[1:] or [''])[0])
                self.out('BATCH_SIM S1 ' + s1)
                break
        return rc, s1

    def run_steps(self, task, steps):
        for name in steps:
            rc, s1 = self.step(task, name)
            if rc != 0 or s1 is not None:
                raise SimError('STEP_FAILED_' + name.upper() + ('_' + s1 if s1 else ''))

    def expect_stop(self, task, steps, stop_step, code):
        for name in steps:
            rc, s1 = self.step(task, name)
            if name == stop_step:
                _require(rc != 0 and s1 == code, 'NEGATIVE_NOT_STOPPED_' + code)
                return
            _require(rc == 0 and s1 is None, 'NEGATIVE_STOPPED_EARLY_' + name.upper())
        raise SimError('NEGATIVE_STEP_NOT_REACHED')

    # -- production ---------------------------------------------------------------------------------
    def production(self, prompt, resume_prompt=None, negative=None):
        task, data, spec, plan = read_prompt(prompt)
        _require(spec.get('kind') == 'production', 'PROMPT_KIND_MISMATCH')
        _require(negative in (None,) + PRODUCTION_NEGATIVES, 'NEGATIVE_INVALID')
        steps = production_steps(spec)
        adopt = spec['start']['mode'] == 'adopt'
        _require(adopt == (resume_prompt is not None), 'RESUME_MISMATCH')
        _require(negative != 'adopt' or adopt, 'NEGATIVE_NEEDS_ADOPT')
        base = spec['base_oid']
        self.make_origin(base)
        self.git('switch', '-q', '-c', START_BRANCH)
        self.install_hooks()
        if adopt:
            r_task, r_data, r_spec, _ = read_prompt(resume_prompt)
            _require(r_spec.get('kind') == 'production' and r_spec['base_oid'] == base, 'RESUME_PROMPT_INVALID')
            _require(r_spec['branch'] == spec['start']['start_branch'], 'RESUME_BRANCH_MISMATCH')
            _require(not r_spec.get('runner_update'), 'RESUME_RUNNER_UPDATE_UNSUPPORTED')
            self.intake(r_task, r_data)
            self.run_steps(r_task, resume_steps(r_spec))
        if negative == 'adopt':
            path = sorted(spec['start']['adopt_hashes'])[0]
            with open(Path(self.work) / path, 'ab') as fh:
                fh.write(b'\n')
        self.intake(task, data)
        if negative == 'adopt':
            self.expect_stop(task, steps, *production_negative(spec, 'adopt'))
            return self.no_commit(base)
        if negative in ('runner', 'author'):
            self.run_steps(task, resume_steps(spec))
            if negative == 'runner':
                target = batch_runner.RUNNER_REL
            else:
                others = sorted(p for p in spec['authors'] if p != batch_runner.RUNNER_REL)
                _require(others, 'NEGATIVE_AUTHOR_UNAVAILABLE')
                target = others[0]
            with open(Path(self.work) / target, 'ab') as fh:
                fh.write(b'\n# injected by batch_sim\n')
            stop_step, code = production_negative(spec, negative)
            self.expect_stop(task, (stop_step,), stop_step, code)
            return self.no_commit(base)
        self.run_steps(task, steps)
        with self.ci_stand_in():
            self.run_steps(task, ('push',))
        if spec.get('bundle_output') is True:
            # Simulates only the pre-push/post-commit pipeline and local CI stand-in.
            # Never run the real bundle helper against host Downloads during rehearsal.
            self.out('BATCH_SIM POST_PUSH_BUNDLE NOT_TESTED')
        self.verify_production(spec, plan)
        self.check_source_unchanged()

    def no_commit(self, base):
        _require(self.git('rev-parse', 'HEAD') == base, 'NEGATIVE_COMMITTED')
        self.check_source_unchanged()

    def verify_production(self, spec, plan):
        base = spec['base_oid']
        head = self.git('rev-parse', 'HEAD')
        _require(self.git('rev-parse', 'HEAD^') == base, 'RESULT_PARENT_MISMATCH')
        changed = sorted(self.git('diff', '--name-only', base, 'HEAD').split())
        _require(changed == sorted(plan['allowed_paths']), 'RESULT_SCOPE_MISMATCH')
        for path, entry in sorted(spec['authors'].items()):
            rc, blob = self.sh(['git', 'cat-file', 'blob', 'HEAD:' + path], merge=False)
            _require(rc == 0, 'RESULT_AUTHOR_MISSING')
            _require(hashlib.sha256(blob).hexdigest() == entry['sha256'], 'RESULT_AUTHOR_HASH_MISMATCH')
        remote = self.git('ls-remote', 'origin', 'refs/heads/' + spec['branch']).split()
        _require(remote[:1] == [head], 'RESULT_REMOTE_MISMATCH')
        rc, _ = self.py('scripts/check_consistency.py')
        _require(rc == 0, 'RESULT_CONSISTENCY_FAILED')
        rc, _ = self.py('scripts/execution_record.py', 'verify')
        _require(rc == 0, 'RESULT_EXECUTION_RECORD_FAILED')
        _require(self.git('status', '--porcelain') == '', 'RESULT_WORKTREE_DIRTY')

    # -- promotion ----------------------------------------------------------------------------------
    def promotion(self, prompt, negative=None):
        task, data, spec, _ = read_prompt(prompt)
        _require(spec.get('kind') == 'promotion', 'PROMPT_KIND_MISMATCH')
        _require(negative in (None,) + tuple(PROMOTION_NEGATIVES), 'NEGATIVE_INVALID')
        base, cand, branch = spec['base_oid'], spec['candidate_oid'], spec['candidate_branch']
        self.make_origin(base, [('refs/heads/' + branch, cand)])
        self.git('switch', '-q', branch, code='CANDIDATE_BRANCH_MISSING')
        self.install_hooks()
        self.intake(task, data)
        expected_main = base
        if negative == 'drift':
            expected_main = self.git('rev-parse', base + '^', code='BASE_HAS_NO_PARENT')
            self.git('-C', self.bare, 'update-ref', 'refs/heads/main', expected_main, cwd=str(self.workdir))
        elif negative == 'dirty':
            (Path(self.work) / 'batch-sim-stray.txt').write_bytes(b'x\n')
        elif negative == 'runner':
            with open(Path(self.work) / batch_runner.RUNNER_REL, 'ab') as fh:
                fh.write(b'\n# injected by batch_sim\n')
        with self.ci_stand_in():
            if negative == 'prompt':
                self.run_steps(task, ('preflight',))
                with open(Path(self.work) / '.git' / (task + '-prompt.txt'), 'ab') as fh:
                    fh.write(b'\ninjected\n')
                self.expect_stop(task, ('verify',), *PROMOTION_NEGATIVES['prompt'])
            elif negative:
                self.expect_stop(task, PROMOTION_STEPS, *PROMOTION_NEGATIVES[negative])
            else:
                self.run_steps(task, PROMOTION_STEPS)
        main = self.git('-C', self.bare, 'rev-parse', 'refs/heads/main', cwd=str(self.workdir))
        if negative:
            _require(main == expected_main, 'NEGATIVE_MAIN_CHANGED')
        else:
            _require(main == cand, 'RESULT_MAIN_MISMATCH')
            _require(not os.path.lexists(Path(self.work) / AUTH_FILE), 'RESULT_AUTH_NOT_CONSUMED')
        self.check_source_unchanged()


def winemu(repo, pytest_args, run=default_run, git_profile='windows', probe_run=default_run):
    """pytest with the Windows emulation plugin, in a temporary isolated HOME/XDG_CONFIG_HOME and Git profile;
    the profile is checked with probe_run (real git) before the tests run."""
    with tempfile.TemporaryDirectory(prefix='batch-sim-winemu-') as root:
        env = isolated_env(root, None, git_profile)
        check_git_profile(probe_run, env, root, git_profile, repo=repo)
        scripts = str(Path(repo).resolve() / 'scripts')
        env['PYTHONPATH'] = scripts + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        rc, out = run([sys.executable, '-m', 'pytest', '-p', 'sim_windows_emulation', '-p', 'no:cacheprovider',
                       *pytest_args], repo, env, STEP_TIMEOUT, True)
    text = out.decode('utf-8', 'replace')
    tail = [l.strip('= ') for l in text.splitlines() if l.strip()][-1:]
    summary = tail[0] if tail and PYTEST_TOTALS.match(tail[0]) else '(summary withheld)'
    print('BATCH_SIM WINEMU ' + summary)
    _require(rc == 0, 'WINEMU_TESTS_FAILED')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Auditor-side isolated batch simulation (B-115).')
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name, negatives in (('production', PRODUCTION_NEGATIVES), ('promotion', tuple(PROMOTION_NEGATIVES))):
        p = sub.add_parser(name)
        p.add_argument('--source', required=True)
        p.add_argument('--prompt', required=True)
        p.add_argument('--workdir', required=True)
        p.add_argument('--locale', default='utf8', choices=sorted(LOCALES))
        p.add_argument('--negative', choices=sorted(negatives))
        p.add_argument('--git-profile', default='isolated', choices=GIT_PROFILES)
        if name == 'production':
            p.add_argument('--resume-prompt')
    w = sub.add_parser('winemu')
    w.add_argument('--repo', required=True)
    w.add_argument('--git-profile', default='windows', choices=GIT_PROFILES)
    w.add_argument('pytest_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'winemu':
            winemu(args.repo, [a for a in args.pytest_args if a != '--'], git_profile=args.git_profile)
            mode = 'winemu git_profile=' + args.git_profile
        else:
            sim = Sim(args.source, args.workdir, args.locale, git_profile=args.git_profile)
            if args.cmd == 'production':
                sim.production(args.prompt, args.resume_prompt, args.negative)
            else:
                sim.promotion(args.prompt, args.negative)
            mode = (args.cmd + (' negative=' + args.negative if args.negative else '') + ' locale=' + args.locale
                    + (' git_profile=windows' if args.git_profile == 'windows' else ''))
        print('BATCH_SIM PASS ' + mode)
    except SimError as e:
        print('BATCH_SIM FAIL ' + str(e))
        return 1
    except (KeyError, TypeError, AttributeError, IndexError):
        print('BATCH_SIM FAIL PROMPT_SHAPE_INVALID')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
