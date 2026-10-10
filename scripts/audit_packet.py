#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit_packet.py
Auditor-side evidence packet for a canonical runner candidate (B-115 pending item 5).

It turns a delivered production prompt, a candidate commit and auditor-supplied remote and CI facts into a fixed,
machine-derived fact list, so the per-batch review does not depend on hand transcription. It is read-only toward
the repository, prints DATA ONLY and is never a verdict: it does not output PASS, does not establish A1, does not
replace reading the raw Actions logs, and is not run by Executors.

Usage:
  python scripts/audit_packet.py --repo <full clone> --prompt <dir>/<TASK_ID>-prompt.txt --candidate <40-hex>
                                 [--remote-refs <file>] [--ci <file>] [--ci-branch <branch>]
                                 [--expect-main base|candidate] [--checks --workdir <empty dir>] [--out <file>]
  python scripts/audit_packet.py --repo <full clone> --prompt <dir>/<TASK_ID>-prompt.txt --preissue
                                 --remote-refs <file> [--out <file>]

Pre-issue mode (--preissue, before a production prompt is delivered, including a re-finalized revision): P_BASE
(base_oid is a commit in the repository), P_MAIN (remote main is at base_oid), P_BRANCH_ABSENT (the prompt's own
branch does not exist remotely), P_NO_SIBLINGS (no other batch branch of the same slice exists remotely, see
R_SIBLINGS). It needs --remote-refs and takes no candidate, CI or checks. A MATCH only says the supplied snapshot
holds no such branch: it is not a lock on the remote and does not replace the runner's own live branch checks.

Facts (each MATCH, CONFLICT or MISSING; nothing is inferred):
  repo     C_FULL_CLONE (not shallow), C_PARENT (the candidate's only parent is base_oid), C_SUBJECT (commit subject
           = spec commit_message), C_PATHS (changed paths base..candidate = PLAN_JSON allowed paths = required paths),
           C_AUTHOR_HASHES (LF SHA-256 of every author blob at the candidate = the spec's value), C_DIFF_CHECK
           (git diff --check base candidate), C_EXEC_RECORD (the candidate's docs/governance/execution-record.json
           names this task, base and plan, and its actual paths are the real diff).
  remote   from --remote-refs (MISSING without it): an AUDITOR_PROVIDED_SNAPSHOT of the auditor's own, current and
           unfiltered "git ls-remote origin" output (it must list HEAD and refs/heads/main, else
           REMOTE_REFS_INCOMPLETE; its SHA-256 is recorded in the packet). R_BRANCH (the spec branch points at the
           candidate), R_MAIN (main points at the base, or at the candidate with --expect-main candidate), R_SIBLINGS
           (no other batch branch of the same slice exists; a pushed earlier or later revision is a duplicate
           candidate). Slice identity follows the branch convention batch/<slice>[-r<n>]-YYMMDD: a remote branch
           belongs to the slice when its name without a trailing date and then without a trailing -r<n> equals the
           slice; a prompt branch without the date suffix cannot be classified and makes the fact a CONFLICT. Other
           renamings of the same work are not recognized.
  checks   with --checks, in a fresh --no-local clone at the candidate inside --workdir (MISSING without it):
           K_CHECK_CONSISTENCY, K_EXECUTION_RECORD_VERIFY, K_FINGERPRINT_VERIFY (exit 0), K_FOCUSED (the spec's
           focused pytest arguments within its limit: exit 0 and a pytest totals line with passes and no failure).
  ci       from --ci (a JSON file the auditor assembles from GitHub; MISSING without it): I_RUN (head_sha =
           candidate, head_branch = the spec branch or --ci-branch, event push, workflow Verify, completed/success),
           I_JOBS (exactly one verify and one gateway-windows job, each completed/success), I_RAW_MARKERS (the markers
           the auditor read in the raw logs: verify "ALL 5 GATES PASSED", gateway-windows "<n> passed").
  CI facts are AUDITOR_PROVIDED input: the tool checks their shape and their binding to the candidate, never their
  truth, and raw-log markers stay the auditor's own reading.

Fail-closed rules: any check that cannot decide (probe failure, timeout, unreadable or malformed input) is a
CONFLICT or makes the tool fail, never a MATCH. Git runs without inherited GIT_* variables, without global or system
configuration and with replacement objects disabled (GIT_NO_REPLACE_OBJECTS and --no-replace-objects). Against the
repository itself it only reads (rev-parse, cat-file -t, and the --mirror --no-local clone); every object fact is read
from that private mirror, whose refs/replace are deleted and which carries none of the source's configuration,
attributes or grafts, so source-side settings cannot change a fact. --checks never runs in the repository itself: it
clones the mirror with --no-local into --workdir, which must be new or empty and outside the repository. Only
production prompts are supported (KIND_UNSUPPORTED).

Trust boundary: --checks executes the candidate's own scripts and tests, so it runs only when C_PATHS and
C_AUTHOR_HASHES are MATCH (the tree is then the base plus the declared author bytes and the two generated JSON files);
otherwise every K_ fact is MISSING with skipped=CONTENT_NOT_VERIFIED. After checkout and before any candidate program
runs, the execution tree itself is checked again (HEAD = candidate, clean with nothing untracked or ignored, changed
paths = plan, every author file a regular file reached without links with the declared LF SHA-256); any difference
makes every K_ fact a CONFLICT with tree=EXECUTION_TREE_MISMATCH and nothing runs. An author path that is not a
regular file at the candidate (link, submodule) counts as absent. Like scripts/batch_sim.py it provides Git isolation only: other
environment variables (including any credentials in the auditor's environment) are inherited by the checks, and the
network is not blocked (accepted residual risk for reviewed code).

Output: one line per fact "AUDIT_PACKET <ID> <STATUS>", then "AUDIT_PACKET RESULT conflicts=<n> missing=<m>", or a
single "AUDIT_PACKET FAIL <CODE>". --out also writes the JSON packet (values are hashes, paths, counts and fixed
codes; file contents are never printed or written). The --out path is checked before any fact is gathered: it must
not exist yet (OUT_EXISTS; never overwritten, created exclusively), and after its parent directory is resolved
(links included) it must lie outside the repository and its git directories (OUT_INSIDE_REPO) and outside --workdir
(OUT_INSIDE_WORKDIR); a new file can be neither an input nor any other existing file. Exit status: 0 when every fact is MATCH, 1 when any fact is a
CONFLICT or MISSING, 2 when the tool could not complete.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import batch_runner  # noqa: E402 - the runner's own prompt parser is the reference
    import bounded_process  # noqa: E402 - shared bounded-execution primitive
finally:
    sys.path.pop(0)

SCHEMA_VERSION = 1
AUTHORITY = 'DATA_ONLY_NOT_A_VERDICT'
MATCH, CONFLICT, MISSING = 'MATCH', 'CONFLICT', 'MISSING'
GIT_TIMEOUT = 600
CHECK_TIMEOUT = 2400
EXEC_RECORD = 'docs/governance/execution-record.json'
REQUIRED_JOBS = ('verify', 'gateway-windows')
VERIFY_MARKER = 'ALL 5 GATES PASSED'
GATEWAY_MARKER = re.compile(r'^[1-9][0-9]* passed$')
PYTEST_TOTALS = re.compile(r'^\d+ [a-z]+(, \d+ [a-z]+)* in [0-9.]+s( \([0-9:]+\))?$')
PYTEST_BAD = re.compile(r'\b\d+ (failed|errors?|xpassed)\b')
REF_LINE = re.compile(r'^([0-9a-f]{40})\t(HEAD|refs/[!-~]+)$')
DATE_SUFFIX = re.compile(r'-[0-9]{6}$')
REVISION_SUFFIX = re.compile(r'-r[0-9]+$')
CHECKS = (
    ('K_CHECK_CONSISTENCY', ['scripts/check_consistency.py']),
    ('K_EXECUTION_RECORD_VERIFY', ['scripts/execution_record.py', 'verify', '--record', EXEC_RECORD, '--repo-root', '.']),
    ('K_FINGERPRINT_VERIFY', ['scripts/fingerprint.py', '--verify']),
)
FACT_IDS = ('C_FULL_CLONE', 'C_PARENT', 'C_SUBJECT', 'C_PATHS', 'C_AUTHOR_HASHES', 'C_DIFF_CHECK', 'C_EXEC_RECORD',
            'R_BRANCH', 'R_MAIN', 'R_SIBLINGS', 'K_CHECK_CONSISTENCY', 'K_EXECUTION_RECORD_VERIFY',
            'K_FINGERPRINT_VERIFY', 'K_FOCUSED', 'I_RUN', 'I_JOBS', 'I_RAW_MARKERS')
PREISSUE_FACT_IDS = ('P_BASE', 'P_MAIN', 'P_BRANCH_ABSENT', 'P_NO_SIBLINGS')


class PacketError(Exception):
    """Fixed failure code; never carries file content."""


def _require(cond, code):
    if not cond:
        raise PacketError(code)


def default_run(args, cwd, env, timeout):
    """Run through bounded_process.run_bounded; return (exit code, stdout bytes). Never raises.
    A timeout returns 124 (125 if the tree kill was not confirmed), a launch failure 127."""
    r = bounded_process.run_bounded(list(args), cwd, timeout, env=env, merge_stderr=False)
    if r.launch_error is not None:
        return 127, b''
    if r.timed_out:
        return (124 if r.kill_status == bounded_process.KILL_TREE_SIGNALLED else 125), b''
    return (r.returncode if r.returncode is not None else 125), r.stdout


def lf_sha256(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def _within(path, root):
    """path equals root or lies under it (root resolved with links; case-insensitive where the platform is)."""
    norm = os.path.normcase
    r = norm(os.path.realpath(root))
    return norm(str(path)) == r or any(norm(str(a)) == r for a in Path(path).parents)


def _is_int(value):
    return type(value) is int


def slice_stem(branch):
    """The slice a batch branch belongs to: the name without its trailing date (-YYMMDD) and then without its
    revision (-r<n>). batch/x-261010, batch/x-r1-261010, batch/x-r2 and batch/x all belong to batch/x."""
    return REVISION_SUFFIX.sub('', DATE_SUFFIX.sub('', branch))


def branch_classified(branch):
    """A prompt's own branch must follow the convention batch/<slice>[-r<n>]-YYMMDD; anything else cannot be
    classified reliably and makes the sibling fact a CONFLICT."""
    return DATE_SUFFIX.search(branch) is not None


def read_prompt(path):
    """Return (task_id, prompt sha256, spec) using the runner's own parser and validator."""
    name = Path(path).name
    _require(name.endswith('-prompt.txt'), 'PROMPT_NAME_INVALID')
    task = name[:-len('-prompt.txt')]
    _require(batch_runner.TASK_RE.match(task) is not None, 'PROMPT_NAME_INVALID')
    try:
        data = Path(path).read_bytes()
        lines = batch_runner.prompt_lines(data)
        kind = json.loads(batch_runner.extract_block(lines, 'BATCH_SPEC_JSON')).get('kind')
    except (OSError, ValueError, AttributeError, batch_runner.Halt):
        raise PacketError('PROMPT_UNREADABLE')
    _require(kind == 'production', 'KIND_UNSUPPORTED')
    try:
        spec = batch_runner.load_spec(lines, task)
    except (ValueError, batch_runner.Halt):
        raise PacketError('PROMPT_SPEC_INVALID')
    return task, hashlib.sha256(data).hexdigest(), spec


def read_remote_refs(path):
    """Parse "git ls-remote" output: {ref: oid}. Any malformed or duplicate line makes the input unusable."""
    try:
        text = Path(path).read_bytes().decode('utf-8')
    except (OSError, UnicodeDecodeError):
        raise PacketError('REMOTE_REFS_UNREADABLE')
    refs = {}
    for line in text.splitlines():
        if not line:
            continue
        m = REF_LINE.match(line)
        _require(m is not None and m.group(2) not in refs, 'REMOTE_REFS_INVALID')
        refs[m.group(2)] = m.group(1)
    _require(bool(refs), 'REMOTE_REFS_INVALID')
    # An unfiltered "git ls-remote origin" always lists HEAD and main; their absence means a filtered snapshot.
    _require('HEAD' in refs and 'refs/heads/main' in refs, 'REMOTE_REFS_INCOMPLETE')
    return refs, hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_ci(path):
    try:
        ci = json.loads(Path(path).read_bytes().decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise PacketError('CI_UNREADABLE')
    _require(isinstance(ci, dict) and ci.get('schema_version') == SCHEMA_VERSION, 'CI_SCHEMA_INVALID')
    return ci


def check_workdir(workdir, repo):
    w = Path(workdir).resolve()
    r = Path(repo).resolve()
    _require(w != r and r not in w.parents and w not in r.parents, 'WORKDIR_OVERLAPS_REPO')
    if w.exists():
        _require(w.is_dir() and not any(w.iterdir()), 'WORKDIR_NOT_EMPTY')
    else:
        w.mkdir(parents=True)
    return w


class Packet:
    def __init__(self, repo, prompt, candidate, remote_refs=None, ci=None, ci_branch=None, expect_main='base',
                 workdir=None, run=default_run, check_timeout=CHECK_TIMEOUT, out=None):
        self.preissue = candidate is None
        if self.preissue:
            _require(remote_refs is not None, 'PREISSUE_NEEDS_REMOTE_REFS')
            _require(ci is None and ci_branch is None and workdir is None and expect_main == 'base',
                     'PREISSUE_OPTION_INVALID')
        else:
            _require(isinstance(candidate, str) and batch_runner.OID_RE.match(candidate) is not None,
                     'CANDIDATE_INVALID')
        _require(expect_main in ('base', 'candidate'), 'EXPECT_MAIN_INVALID')
        self.repo = str(Path(repo).resolve())
        self.task, self.prompt_sha, self.spec = read_prompt(prompt)
        self.base = self.spec['base_oid']
        self.candidate = candidate
        self.remote_refs, self.remote_sha = read_remote_refs(remote_refs) if remote_refs else (None, None)
        self.ci = read_ci(ci) if ci else None
        self.ci_branch = ci_branch or self.spec['branch']
        self.expect_main = expect_main
        self.workdir = check_workdir(workdir, repo) if workdir else None
        self.run = run
        self.check_timeout = check_timeout
        self.facts = {}
        self._tmp = tempfile.mkdtemp(prefix='audit-packet-')
        cfg = os.path.join(self._tmp, 'empty-gitconfig')
        with open(cfg, 'wb'):
            pass
        self.env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        self.env.update({'GIT_CONFIG_GLOBAL': cfg, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'})
        self.env['GIT_NO_REPLACE_OBJECTS'] = '1'
        self.mirror = None
        self.out = None
        if out is not None:
            try:
                self.out = self.check_out(out)
            except PacketError:
                self.close()
                raise

    def check_out(self, out):
        """The JSON output must be a new file (so never an input or any existing file) outside the repository, its
        git directories and the work directory; the parent directory is resolved (links included) first."""
        p = Path(out)
        _require(not os.path.lexists(str(p)), 'OUT_EXISTS')
        try:
            target = p.parent.resolve(strict=True) / p.name
        except (OSError, RuntimeError):
            raise PacketError('OUT_INVALID')
        roots = [self.repo]
        for flag in ('--absolute-git-dir', '--git-common-dir'):
            rc, got = self.run(['git', '-C', self.repo, 'rev-parse', '--path-format=absolute', flag], self._tmp,
                               self.env, GIT_TIMEOUT)
            _require(rc == 0 and got.strip(), 'OUT_INVALID')
            roots.append(got.decode('utf-8', 'strict').strip())
        for root in roots:
            _require(not _within(target, root), 'OUT_INSIDE_REPO')
        if self.workdir is not None:
            _require(not _within(target, str(self.workdir)), 'OUT_INSIDE_WORKDIR')
        return target

    def write_out(self, result):
        with open(str(self.out), 'xb') as f:
            f.write((json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + '\n').encode('utf-8'))

    def close(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- primitives -------------------------------------------------------------------------------------
    def git(self, *args, cwd=None, code='GIT_FAILED'):
        rc, out = self.run(['git', '--no-replace-objects', '-C', cwd or self.mirror or self.repo, *args], self._tmp,
                           self.env, GIT_TIMEOUT)
        _require(rc == 0, code)
        return out

    def git_text(self, *args, code='GIT_FAILED'):
        return self.git(*args, code=code).decode('utf-8', 'strict').strip()

    def fact(self, fid, status, **detail):
        assert fid in self.fact_ids() and status in (MATCH, CONFLICT, MISSING)
        self.facts[fid] = {'status': status, 'detail': detail}

    def fact_ids(self):
        return PREISSUE_FACT_IDS if self.preissue else FACT_IDS

    def siblings_fact(self, fid):
        branch = self.spec['branch']
        if not branch_classified(branch):
            self.fact(fid, CONFLICT, unclassified=True, siblings=[])
            return
        stem = slice_stem(branch)
        own = 'refs/heads/' + branch
        siblings = sorted(r[len('refs/heads/'):] for r in self.remote_refs if r.startswith('refs/heads/batch/')
                          and r != own and slice_stem(r[len('refs/heads/'):]) == stem)
        self.fact(fid, CONFLICT if siblings else MATCH, unclassified=False, siblings=siblings)

    # -- pre-issue facts ---------------------------------------------------------------------------------
    def preissue_facts(self):
        rc, out = self.run(['git', '--no-replace-objects', '-C', self.repo, 'cat-file', '-t', self.base], self._tmp,
                           self.env, GIT_TIMEOUT)
        self.fact('P_BASE', MATCH if rc == 0 and out.strip() == b'commit' else CONFLICT)
        main = self.remote_refs.get('refs/heads/main')
        self.fact('P_MAIN', MATCH if main == self.base else CONFLICT,
                  at='base' if main == self.base else 'absent' if main is None else 'other')
        own = self.remote_refs.get('refs/heads/' + self.spec['branch'])
        self.fact('P_BRANCH_ABSENT', MATCH if own is None else CONFLICT, present=own is not None)
        self.siblings_fact('P_NO_SIBLINGS')

    # -- repository facts --------------------------------------------------------------------------------
    def make_mirror(self):
        """Every object fact is read from a fresh --mirror --no-local copy with its replacement refs deleted and
        replacement objects disabled: the source's own configuration, attributes, grafts and refs/replace can change
        what git reports there, but never in this copy. The checks clone is made from the same copy."""
        mirror = os.path.join(self._tmp, 'source.git')
        self.git('clone', '-q', '--mirror', '--no-local', '--template=', self.repo, mirror, cwd=self._tmp,
                 code='MIRROR_FAILED')
        for ref in self.git('for-each-ref', '--format=%(refname)', 'refs/replace', cwd=mirror).decode(
                'utf-8', 'strict').split():
            self.git('update-ref', '-d', ref, cwd=mirror, code='MIRROR_FAILED')
        _require(not self.git('for-each-ref', 'refs/replace', cwd=mirror).strip(), 'MIRROR_FAILED')
        self.mirror = mirror

    def repo_facts(self):
        base, cand, spec = self.base, self.candidate, self.spec
        shallow = self.git_text('rev-parse', '--is-shallow-repository')
        self.fact('C_FULL_CLONE', MATCH if shallow == 'false' else CONFLICT, shallow=shallow if shallow in ('true', 'false') else 'INVALID')
        self.make_mirror()
        _require(self.git_text('cat-file', '-t', base, code='BASE_NOT_IN_REPO') == 'commit', 'BASE_NOT_IN_REPO')
        _require(self.git_text('cat-file', '-t', cand, code='CANDIDATE_NOT_IN_REPO') == 'commit', 'CANDIDATE_NOT_IN_REPO')
        parents = self.git_text('rev-list', '--parents', '-n', '1', cand).split()[1:]
        self.fact('C_PARENT', MATCH if parents == [base] else CONFLICT, parents=parents)
        subject = self.git_text('log', '-1', '--format=%s', cand)
        self.fact('C_SUBJECT', MATCH if subject == spec['commit_message'] else CONFLICT)
        actual = sorted(p for p in self.git('diff', '--name-only', '-z', '--no-renames', base, cand)
                        .decode('utf-8', 'strict').split('\0') if p)
        allowed = batch_runner.allowed_paths(spec)
        self.fact('C_PATHS', MATCH if actual == allowed else CONFLICT, extra=sorted(set(actual) - set(allowed)),
                  missing=sorted(set(allowed) - set(actual)))
        self.actual = actual
        present = self.tree_files(cand)
        mismatched = []
        for path in sorted(spec['authors']):
            if path not in present:
                mismatched.append(path)
                continue
            data = self.git('cat-file', 'blob', cand + ':' + path, code='BLOB_UNREADABLE')
            if lf_sha256(data) != spec['authors'][path]['sha256']:
                mismatched.append(path)
        self.fact('C_AUTHOR_HASHES', CONFLICT if mismatched else MATCH, mismatched=mismatched,
                  checked=len(spec['authors']))
        rc, _ = self.run(['git', '--no-replace-objects', '-C', self.mirror, 'diff', '--check', base, cand], self._tmp,
                         self.env, GIT_TIMEOUT)
        self.fact('C_DIFF_CHECK', MATCH if rc == 0 else CONFLICT, exit_code=rc)
        self.fact('C_EXEC_RECORD', *self.exec_record(present, allowed, actual))

    def tree_files(self, rev):
        """Paths of regular files (mode 100644 or 100755) at rev; links, submodules and other entries are left out,
        so an author path that is not a regular file counts as absent."""
        files = set()
        for entry in self.git('ls-tree', '-r', '-z', '--full-tree', rev).decode('utf-8', 'strict').split('\0'):
            if not entry:
                continue
            meta, _, path = entry.partition('\t')
            parts = meta.split(' ')
            _require(len(parts) == 3 and path, 'TREE_UNREADABLE')
            if parts[0] in ('100644', '100755') and parts[1] == 'blob':
                files.add(path)
        return files

    def exec_record(self, present, allowed, actual):
        if EXEC_RECORD not in present:
            return (CONFLICT,)
        data = self.git('cat-file', 'blob', self.candidate + ':' + EXEC_RECORD, code='BLOB_UNREADABLE')
        try:
            rec = json.loads(data.decode('utf-8'))
            ok = (isinstance(rec, dict) and rec.get('task_id') == self.task and rec.get('base_oid') == self.base
                  and isinstance(rec.get('plan'), dict) and isinstance(rec.get('actual'), dict)
                  and sorted(rec['plan'].get('allowed_paths') or []) == allowed
                  and sorted(rec['plan'].get('required_paths') or []) == allowed
                  and sorted(rec['actual'].get('changed_paths') or []) == actual)
        except (UnicodeDecodeError, ValueError, TypeError):
            ok = False
        return (MATCH if ok else CONFLICT,)

    # -- remote facts ------------------------------------------------------------------------------------
    def remote_facts(self):
        if self.remote_refs is None:
            for fid in ('R_BRANCH', 'R_MAIN', 'R_SIBLINGS'):
                self.fact(fid, MISSING)
            return
        refs, branch = self.remote_refs, self.spec['branch']
        got = refs.get('refs/heads/' + branch)
        self.fact('R_BRANCH', MATCH if got == self.candidate else CONFLICT, present=got is not None)
        want = self.base if self.expect_main == 'base' else self.candidate
        main = refs.get('refs/heads/main')
        self.fact('R_MAIN', MATCH if main == want else CONFLICT, expect=self.expect_main,
                  at=('base' if main == self.base else 'candidate' if main == self.candidate
                      else 'absent' if main is None else 'other'))
        self.siblings_fact('R_SIBLINGS')

    # -- local checks ------------------------------------------------------------------------------------
    def checks(self):
        ids = [fid for fid, _ in CHECKS] + ['K_FOCUSED']
        if self.workdir is None:
            for fid in ids:
                self.fact(fid, MISSING)
            return
        if self.facts['C_PATHS']['status'] != MATCH or self.facts['C_AUTHOR_HASHES']['status'] != MATCH:
            # Never execute candidate content that is not exactly base + the declared author bytes.
            for fid in ids:
                self.fact(fid, MISSING, skipped='CONTENT_NOT_VERIFIED')
            return
        clone = str(self.workdir / 'clone')
        self.git('clone', '-q', '--no-local', '--template=', self.mirror, clone, cwd=str(self.workdir),
                 code='CHECK_CLONE_FAILED')
        self.git('checkout', '-q', '--detach', self.candidate, cwd=clone, code='CHECK_CHECKOUT_FAILED')
        if not self.execution_tree_verified(clone):
            for fid in ids:
                self.fact(fid, CONFLICT, tree='EXECUTION_TREE_MISMATCH')
            return
        for fid, args in CHECKS:
            rc, _ = self.run([sys.executable, *args], clone, self.env, self.check_timeout)
            self.fact(fid, MATCH if rc == 0 else CONFLICT, exit_code=rc)
        focused = self.spec.get('focused')
        if focused is None:
            self.fact('K_FOCUSED', MATCH, focused='NONE')
            return
        rc, out = self.run([sys.executable, '-m', 'pytest', *focused['pytest_args']], clone, self.env,
                           focused['limit_sec'])
        totals = [ln.strip().strip('=').strip() for ln in out.decode('utf-8', 'replace').splitlines()]
        totals = [ln for ln in totals if PYTEST_TOTALS.match(ln)]
        line = totals[-1] if totals else None
        ok = rc == 0 and line is not None and ' passed' in ' ' + line and not PYTEST_BAD.search(line)
        self.fact('K_FOCUSED', MATCH if ok else CONFLICT, exit_code=rc, totals=line)

    def git_text_in(self, cwd, *args):
        return self.git(*args, cwd=cwd).decode('utf-8', 'strict').strip()

    def execution_tree_verified(self, clone):
        """Before any candidate program runs: HEAD is the candidate, the work tree is clean with nothing untracked,
        the changed paths are the plan's, and every author file on disk is a regular file reached without links whose
        LF SHA-256 is the declared value."""
        if self.git_text_in(clone, 'rev-parse', 'HEAD') != self.candidate:
            return False
        if self.git('status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignored', cwd=clone).strip(b'\0'):
            return False
        actual = sorted(p for p in self.git('diff', '--name-only', '-z', '--no-renames', self.base, 'HEAD', cwd=clone)
                        .decode('utf-8', 'strict').split('\0') if p)
        if actual != batch_runner.allowed_paths(self.spec):
            return False
        for path, entry in sorted(self.spec['authors'].items()):
            try:
                target = batch_runner.author_target(clone, path)
                if not stat.S_ISREG(os.lstat(target).st_mode):
                    return False
                with open(target, 'rb') as f:
                    if lf_sha256(f.read()) != entry['sha256']:
                        return False
            except (OSError, batch_runner.Halt):
                return False
        return True

    # -- CI facts ----------------------------------------------------------------------------------------
    def ci_facts(self):
        ci = self.ci
        if ci is None:
            for fid in ('I_RUN', 'I_JOBS', 'I_RAW_MARKERS'):
                self.fact(fid, MISSING)
            return
        run_ok = (ci.get('head_sha') == self.candidate and ci.get('head_branch') == self.ci_branch
                  and ci.get('event') == 'push' and ci.get('workflow_name') == 'Verify'
                  and ci.get('status') == 'completed' and ci.get('conclusion') == 'success'
                  and _is_int(ci.get('run_id')) and _is_int(ci.get('run_attempt')) and ci['run_attempt'] >= 1)
        self.fact('I_RUN', MATCH if run_ok else CONFLICT, run_id=ci['run_id'] if _is_int(ci.get('run_id')) else None,
                  run_attempt=ci['run_attempt'] if _is_int(ci.get('run_attempt')) else None, branch=self.ci_branch)
        jobs = ci.get('jobs')
        jobs_ok = isinstance(jobs, list) and all(isinstance(j, dict) for j in jobs)
        if jobs_ok:
            for name in REQUIRED_JOBS:
                found = [j for j in jobs if j.get('name') == name]
                jobs_ok = jobs_ok and len(found) == 1 and found[0].get('status') == 'completed' \
                    and found[0].get('conclusion') == 'success'
        self.fact('I_JOBS', MATCH if jobs_ok else CONFLICT)
        markers = ci.get('raw_markers')
        if not isinstance(markers, dict) or not markers:
            self.fact('I_RAW_MARKERS', MISSING)
            return
        verify = markers.get('verify')
        gateway = markers.get('gateway-windows')
        ok = verify == VERIFY_MARKER and isinstance(gateway, str) and GATEWAY_MARKER.match(gateway) is not None
        self.fact('I_RAW_MARKERS', MATCH if ok else CONFLICT,
                  gateway=gateway if isinstance(gateway, str) and GATEWAY_MARKER.match(gateway) else None)

    # -- assembly ----------------------------------------------------------------------------------------
    def build(self):
        if self.preissue:
            self.preissue_facts()
        else:
            self.repo_facts()
            self.remote_facts()
            self.checks()
            self.ci_facts()
        ids = self.fact_ids()
        _require(set(self.facts) == set(ids), 'FACT_SET_INCOMPLETE')
        conflicts = [f for f in ids if self.facts[f]['status'] == CONFLICT]
        missing = [f for f in ids if self.facts[f]['status'] == MISSING]
        return {'schema_version': SCHEMA_VERSION, 'authority': AUTHORITY, 'task_id': self.task,
                'mode': 'preissue' if self.preissue else 'candidate',
                'prompt_sha256': self.prompt_sha, 'base_oid': self.base, 'candidate_oid': self.candidate,
                'branch': self.spec['branch'], 'ci_origin': 'AUDITOR_PROVIDED' if self.ci else None,
                'remote_origin': 'AUDITOR_PROVIDED_SNAPSHOT' if self.remote_refs else None,
                'remote_refs_sha256': self.remote_sha,
                'facts': [dict(id=f, **self.facts[f]) for f in ids],
                'summary': {'conflicts': conflicts, 'missing': missing}}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Auditor-side evidence packet (B-115); DATA ONLY, never a verdict.')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--candidate')
    parser.add_argument('--preissue', action='store_true')
    parser.add_argument('--remote-refs')
    parser.add_argument('--ci')
    parser.add_argument('--ci-branch')
    parser.add_argument('--expect-main', default='base')
    parser.add_argument('--checks', action='store_true')
    parser.add_argument('--workdir')
    parser.add_argument('--out')
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        print('AUDIT_PACKET FAIL USAGE')
        return 2
    if args.checks != (args.workdir is not None):
        print('AUDIT_PACKET FAIL CHECKS_NEED_WORKDIR')
        return 2
    if args.preissue == (args.candidate is not None):
        print('AUDIT_PACKET FAIL MODE_INVALID')
        return 2
    packet = None
    try:
        packet = Packet(args.repo, args.prompt, args.candidate, args.remote_refs, args.ci, args.ci_branch,
                        args.expect_main, args.workdir, out=args.out)
        result = packet.build()
        if args.out:
            packet.write_out(result)
    except PacketError as e:
        print('AUDIT_PACKET FAIL ' + str(e))
        return 2
    except (OSError, UnicodeDecodeError):
        print('AUDIT_PACKET FAIL IO_ERROR')
        return 2
    finally:
        if packet is not None:
            packet.close()
    for fact in result['facts']:
        print('AUDIT_PACKET ' + fact['id'] + ' ' + fact['status'])
    s = result['summary']
    print('AUDIT_PACKET RESULT conflicts=' + str(len(s['conflicts'])) + ' missing=' + str(len(s['missing'])))
    return 1 if s['conflicts'] or s['missing'] else 0


if __name__ == '__main__':
    sys.exit(main())
