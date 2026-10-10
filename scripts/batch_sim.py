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
                              [--negative runner|author|adopt]
  python scripts/batch_sim.py promotion  --source <repo> --prompt <file> --workdir <empty dir>
                              [--locale utf8|posix] [--negative drift|dirty|runner|prompt]
  python scripts/batch_sim.py winemu     --repo <repo> -- <pytest arguments>

Production: origin main = the prompt's base_oid; the work clone starts on batch/sim-start (or, with
--resume-prompt, first runs preflight..apply of the stopped batch, rebuilding its stop state for an adopt start).
Steps preflight..postcommit run in order; push runs with the GitHub CI query replaced by a fixed success stand-in
inside the work clone only (the simulation has no GitHub access). Result checks: parent = base, changed paths =
PLAN_JSON allowed paths, every author file at HEAD has the declared SHA-256 (LF), origin branch = HEAD,
check_consistency and execution_record verify exit 0, clean worktree.
Promotion: origin main = base_oid, origin candidate branch = candidate_oid; steps preflight, verify, promote,
postmain; result: origin main = candidate and the single-use authorization file is consumed.
Negatives inject one fault and require the documented S1 line at the documented step, with nothing committed
(production) or origin main exactly at its expected value (promotion: the injected parent for drift, Base otherwise).

Isolation: the work directory must be new or empty and outside the source; every git command runs without any
inherited GIT_* variable and with an empty global configuration (no system configuration), clones use an empty
template; the work tree, git directory and both origin URLs are verified to be the simulation's own paths, and the
source repository's refs must be unchanged at the end. Every command runs through bounded_process.run_bounded
(own process group, output to temporary files, whole tree terminated on timeout). S1 codes are printed only when
they belong to the runner's own constant vocabulary; anything else is printed as S1_UNLISTED.
winemu runs pytest with scripts/sim_windows_emulation.py loaded (an emulation, never native Windows evidence).

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import batch_runner  # noqa: E402 - the runner's own prompt parser is the reference
    import bounded_process  # noqa: E402 - shared bounded-execution primitive (kills the whole process tree)
finally:
    sys.path.pop(0)

PRODUCTION_STEPS = ('preflight', 'setup', 'e24', 'apply', 'focused', 'generate', 'precommit', 'stage', 'commit',
                    'postcommit')
RESUME_STEPS = ('preflight', 'setup', 'e24', 'apply')
PROMOTION_STEPS = ('preflight', 'verify', 'promote', 'postmain')
STEP_TIMEOUT = 3600
GIT_TIMEOUT = 600
START_BRANCH = 'batch/sim-start'
SIM_IDENTITY = ('-c', 'user.name=HH.AI', '-c', 'user.email=sim@example.invalid')
LOCALES = {
    'utf8': {},
    'posix': {'LC_ALL': 'POSIX', 'LANG': 'POSIX', 'PYTHONCOERCECLOCALE': '0', 'PYTHONUTF8': '0'},
}
# Expected (step, S1 code) for each injected fault.
PRODUCTION_NEGATIVES = {
    'runner': ('focused', 'CONTROL_BINDING_DRIFT'),
    'author': ('focused', 'FOCUSED_AUTHOR_DRIFT'),
    'adopt': ('setup', 'ADOPT_HASH_MISMATCH'),
}
PROMOTION_NEGATIVES = {
    'drift': ('verify', 'MAIN_DRIFT'),
    'dirty': ('verify', 'DIRTY_WORKTREE'),
    'runner': ('preflight', 'RUNNER_MODIFIED'),
    'prompt': ('verify', 'CONTROL_BINDING_DRIFT'),
}
CI_STUB = ('import runpy, sys\n'
           'if sys.argv[1:2] == ["ci-status"]:\n'
           '    sys.exit(0)  # SIMULATION ONLY: no GitHub access in the isolated clone\n'
           'runpy.run_path(".git/batch-sim-vp-real.py", run_name="__main__")\n')
AUTH_FILE = '.git/hhai-sensitive-push-auth.json'
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


class Sim:
    def __init__(self, source, workdir, locale='utf8', run=default_run, out=print):
        _require(locale in LOCALES, 'LOCALE_INVALID')
        self.source = str(Path(source).resolve())
        self.workdir = check_workdir(workdir, source)
        self.bare = str(self.workdir / 'origin.git')
        self.work = str(self.workdir / 'work')
        self.downloads = self.workdir / 'downloads'
        # Git isolation: no inherited GIT_* variable (GIT_DIR, GIT_WORK_TREE, GIT_CONFIG_*, ...) and no global or
        # system configuration (url rewrites, push URLs, hooksPath, templates); the simulation's own empty file
        # is the only global configuration.
        self.env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        self.env.update(LOCALES[locale])
        self.gitconfig = self.workdir / 'isolated-gitconfig'
        self.gitconfig.write_bytes(b'')
        self.env.update({'GIT_CONFIG_GLOBAL': str(self.gitconfig), 'GIT_CONFIG_NOSYSTEM': '1',
                         'GIT_TERMINAL_PROMPT': '0'})
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
        return self.git('-C', self.source, 'for-each-ref', '--format=%(refname) %(objectname)', cwd=str(self.workdir),
                        code='SOURCE_UNREADABLE')

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
        self.check_locations()

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
            if line.startswith('S1 ') and not line.startswith('S1 NONE') and ' | ' in line:
                s1 = known_s1(line.split(' | ')[0][3:].strip())
                self.out('BATCH_SIM S1 ' + s1)
                break
        return rc, s1

    def run_steps(self, task, steps):
        for name in steps:
            rc, s1 = self.step(task, name)
            if rc != 0:
                raise SimError('STEP_FAILED_' + name.upper() + ('_' + s1 if s1 else ''))

    def expect_stop(self, task, steps, stop_step, code):
        for name in steps:
            rc, s1 = self.step(task, name)
            if name == stop_step:
                _require(rc != 0 and s1 == code, 'NEGATIVE_NOT_STOPPED_' + code)
                return
            _require(rc == 0, 'NEGATIVE_STOPPED_EARLY_' + name.upper())
        raise SimError('NEGATIVE_STEP_NOT_REACHED')

    # -- production ---------------------------------------------------------------------------------
    def production(self, prompt, resume_prompt=None, negative=None):
        task, data, spec, plan = read_prompt(prompt)
        _require(spec.get('kind') == 'production', 'PROMPT_KIND_MISMATCH')
        _require(negative in (None,) + tuple(PRODUCTION_NEGATIVES), 'NEGATIVE_INVALID')
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
            self.intake(r_task, r_data)
            self.run_steps(r_task, RESUME_STEPS)
        if negative == 'adopt':
            path = sorted(spec['start']['adopt_hashes'])[0]
            with open(Path(self.work) / path, 'ab') as fh:
                fh.write(b'\n')
        self.intake(task, data)
        if negative == 'adopt':
            self.expect_stop(task, PRODUCTION_STEPS, *PRODUCTION_NEGATIVES['adopt'])
            return self.no_commit(base)
        if negative in ('runner', 'author'):
            self.run_steps(task, RESUME_STEPS)
            if negative == 'runner':
                target = batch_runner.RUNNER_REL
            else:
                target = sorted(p for p in spec['authors'] if p != batch_runner.RUNNER_REL)[0]
            with open(Path(self.work) / target, 'ab') as fh:
                fh.write(b'\n# injected by batch_sim\n')
            self.expect_stop(task, ('focused',), *PRODUCTION_NEGATIVES[negative])
            return self.no_commit(base)
        self.run_steps(task, PRODUCTION_STEPS)
        with self.ci_stand_in():
            self.run_steps(task, ('push',))
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


def winemu(repo, pytest_args, run=default_run):
    env = dict(os.environ)
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
    for name, negatives in (('production', PRODUCTION_NEGATIVES), ('promotion', PROMOTION_NEGATIVES)):
        p = sub.add_parser(name)
        p.add_argument('--source', required=True)
        p.add_argument('--prompt', required=True)
        p.add_argument('--workdir', required=True)
        p.add_argument('--locale', default='utf8', choices=sorted(LOCALES))
        p.add_argument('--negative', choices=sorted(negatives))
        if name == 'production':
            p.add_argument('--resume-prompt')
    w = sub.add_parser('winemu')
    w.add_argument('--repo', required=True)
    w.add_argument('pytest_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'winemu':
            winemu(args.repo, [a for a in args.pytest_args if a != '--'])
            mode = 'winemu'
        else:
            sim = Sim(args.source, args.workdir, args.locale)
            if args.cmd == 'production':
                sim.production(args.prompt, args.resume_prompt, args.negative)
            else:
                sim.promotion(args.prompt, args.negative)
            mode = args.cmd + (' negative=' + args.negative if args.negative else '') + ' locale=' + args.locale
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
