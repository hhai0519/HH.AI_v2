#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-115 Q2 auditor-only five-stage, resumable draft preflight.

The user worktree and remote are NEVER written. Takes a clean local full Base clone,
reviewed author patch, and exact PLAN_JSON. All writes go under a new isolated --workdir.
Stages are ordered generate, as_if, base_diff_verify_all, traceability, check20.
No Git commit/push, no post-push bundle, no Windows-native claim. A separate canonical
batch_sim MINISIM remains mandatory before Executor author-prompt issue.
"""
import argparse
import ast
import difflib
import time
import xml.etree.ElementTree as ET
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

# Canonical tree-bounded runner; a timeout never leaves live pytest descendants by design.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bounded_process
import batch_sim
import batch_runner
import production_template

STAGES = ('generate', 'as_if', 'base_diff_verify_all', 'traceability', 'check20', 'winemu_base_diff')
GENERATED = ('docs/fingerprints/exec-latest.json', 'docs/governance/execution-record.json')
STATUS = ('docs/AUDIT-LOG.md', 'docs/EXEC-LOG.md', 'docs/TASKBOARD.md', 'docs/refactor-backlog.md')
HEX40 = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
SHA_LABEL = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:[A-Za-z0-9_]*SHA[-_ ]?256)(?:\s*[:=：]\s*|\s+|\s*[（(]\s*)[`\"']?([0-9a-fA-F]{8,}(?:…|\.{3}|[0-9A-Za-z_]*))")
OID_LABEL = re.compile(r"(?i)\b(?:BASE_OID|CANDIDATE_OID|COMMIT_OID|MAIN_OID|main|parent)(?:\s*[:=：]\s*|\s+)[`\"']?([0-9a-fA-F]{8,}(?:…|\.{3}|[0-9A-Za-z_]*))")
GATE_FAIL = re.compile(r'FAILED gates \(\d+\): ([a-z_, ]+)', re.MULTILINE)
FAIL_ID = re.compile(r'^(?:FAILED|ERROR)\s+([A-Za-z0-9_./-]+\.py::[^\s]+)', re.MULTILINE)

class DraftError(Exception):
    pass

def require(ok, code):
    if not ok:
        raise DraftError(code)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def sha_file(path):
    return sha(Path(path).read_bytes())

def cmd(args, cwd, *, timeout=240, log=None, env=None):
    # Never print captured stdout (it may contain test secrets). Only isolated logs hold it.
    r = bounded_process.run_bounded(list(args), str(cwd), timeout, env=env, merge_stderr=True)
    data = r.stdout
    if log:
        Path(log).write_bytes(data)
    if r.launch_error is not None:
        return 127, data
    if r.timed_out:
        return (124 if r.kill_status == bounded_process.KILL_TREE_SIGNALLED else 125), data
    return (r.returncode if r.returncode is not None else 125), data


def git(repo, *args, timeout=120):
    rc, output = cmd(['git', '-C', str(repo), *args], repo, timeout=timeout)
    require(rc == 0, 'GIT_NONZERO')
    return output.decode('utf-8', 'strict').strip()

def validate_plan(data, base):
    require(isinstance(data, dict) and data.get('base_oid') == base, 'PLAN_BASE_MISMATCH')
    require(isinstance(data.get('task_id'), str) and re.fullmatch(r'[A-Za-z0-9_-]+', data['task_id']), 'TASK_INVALID')
    allowed, needed = data.get('allowed_paths'), data.get('required_paths')
    require(isinstance(allowed, list) and isinstance(needed, list) and all(isinstance(x, str) for x in allowed+needed), 'PLAN_PATHS_INVALID')
    require(len(allowed) == len(set(allowed)) and set(needed).issubset(allowed), 'PLAN_PATHS_INVALID')
    for path in allowed:
        parts = path.split('/')
        require(not path.startswith('/') and len(parts)>0 and all(x not in ('', '.', '..') for x in parts)
                and '.git' not in parts and '\\' not in path and ':' not in path, 'PLAN_PATHS_UNSAFE')
    require(set(GENERATED).issubset(allowed), 'PLAN_MISSING_GENERATED')
    return set(allowed)

def lint_added_sha_labels(diff, paths=STATUS):
    """Check new state-document lines only, not immutable historical rows or negative fixtures.
    `SHA256=...` => 64 hex; `main=...`/`BASE_OID=...` => 40 hex.
    """
    bad=[]
    file=None
    for line in diff.decode('utf-8','strict').splitlines():
        if line.startswith('+++ b/'):
            file=line[6:]
        elif line.startswith('+') and not line.startswith('+++') and file in paths:
            text=line[1:]
            for rx, length in ((SHA_LABEL, 64),(OID_LABEL,40)):
                for m in rx.finditer(text):
                    value=m.group(1)
                    if len(value)!=length or not re.fullmatch('[0-9a-fA-F]+',value):
                        bad.append({'file':file,'field':m.group(0).split(value)[0],'actual_length':len(value)})
    return bad

def fail_ids(log_bytes):
    text=log_bytes.decode('utf-8','replace')
    return sorted(set(FAIL_ID.findall(text)))

def fingerprint(source, patch, plan, scripts_dir, workspace, *, definition=None, prompt=None):
    tools = [scripts_dir / name for name in ('draft_precheck.py','check_consistency.py',
             'execution_record.py','fingerprint.py','verify_all.py','generate_rule_traceability.py','impact_scan.py',
             'history_guard.py','batch_sim.py','production_template.py','prompt_builder.py')]
    tool_h=sha(json.dumps({p.name:sha_file(p) for p in tools},sort_keys=True).encode('utf8'))
    env_data={'os':platform.platform(),'python':sys.version, 'python_executable':sys.executable,
              'uid':getattr(os,'getuid',lambda:None)(), 'cwd_path_bytes':len(str(workspace).encode()),
              'git': cmd(['git','--version'],source)[1].decode('utf-8','replace').strip(),
              'node': cmd(['node','--version'],source)[1].decode('utf-8','replace').strip()}
    env_h=sha(json.dumps(env_data,sort_keys=True).encode('utf8'))
    hashes={'BASE_OID':git(source,'rev-parse','HEAD'), 'AUTHOR_SHA256':sha_file(patch),
            'PLAN_SHA256':sha_file(plan),'TOOL_SHA256':tool_h,'ENV_SHA256':env_h}
    hashes['DEFINITION_SHA256']=sha_file(definition) if definition else 'NONE'
    hashes['PROMPT_SHA256']=sha_file(prompt) if prompt else 'NONE'
    hashes['CACHE_KEY_SHA256']=sha(json.dumps(hashes,sort_keys=True).encode('utf8'))
    return hashes


def assert_baseclone(baseclone, base_oid, expected_tree=None):
    # Verify the source of the baseline on every resume and immediately before Base tests.
    def probe(*args):
        rc, output = cmd(['git', '-C', str(baseclone), *args], baseclone)
        require(rc == 0, 'RESUME_BASECLONE_DRIFT')
        return output.decode('utf-8', 'strict').strip()
    require((baseclone/'.git').exists() and
            probe('rev-parse', 'HEAD') == base_oid and
            not probe('status', '--porcelain=v1', '--untracked-files=all'),
            'RESUME_BASECLONE_DRIFT')
    tree = probe('rev-parse', 'HEAD^{tree}')
    require(HEX40.fullmatch(tree) is not None and
            (expected_tree is None or tree == expected_tree), 'RESUME_BASECLONE_DRIFT')
    return tree

def candidate_digest(work):
    # Tracked diff alone omits new (untracked) author files; bind their bytes as well.
    repo=work/'candclone'
    h=hashlib.sha256(cmd(['git','-C',str(repo),'diff','--binary','HEAD'],work)[1])
    for rel in sorted(git(repo,'ls-files','--others','--exclude-standard').splitlines()):
        h.update(b'\0'+rel.encode('utf-8')+b'\0'+bytes.fromhex(sha_file(repo/rel)))
    return h.hexdigest()

def atomic_json(path, data):
    path=Path(path)
    tmp=path.with_suffix('.writing')
    require(not tmp.exists(), 'STATE_TEMP_EXISTS')
    with open(tmp,'xb') as f:
        f.write((json.dumps(data,indent=2,ensure_ascii=False,sort_keys=True)+'\n').encode('utf-8'))
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def parse_gate(log):
    raw=Path(log).read_bytes()
    text=raw.decode('utf-8','replace')
    return {'EXIT_REASON': 'ALL_5_PASS' if re.search(r'(?m)^ALL 5 GATES PASSED\s*$', text) else 'NONZERO',
            'FAIL_IDS':fail_ids(raw),'FAILED_GATES': sorted((GATE_FAIL.search(text).group(1).split(', ')) if GATE_FAIL.search(text) else []), 'LOG_SHA256':sha(raw)}

def classify_base_candidate(base_rc, candidate_rc, base_gate, candidate_gate):
    """Never turn two matching nonzero gate outcomes into a green verify_all."""
    require(base_rc == candidate_rc, 'VERIFY_EXIT_DIFFERENT')
    require(base_rc not in (124, 125, 127) and candidate_rc not in (124, 125, 127),
            'VERIFY_TIMEOUT_OR_LAUNCH_FAILED')
    require(base_gate['FAILED_GATES'] == candidate_gate['FAILED_GATES'], 'VERIFY_FAILED_GATES_DIFFERENT')
    if candidate_rc == 0:
        require(base_gate.get('EXIT_REASON') == 'ALL_5_PASS' and
                candidate_gate.get('EXIT_REASON') == 'ALL_5_PASS', 'VERIFY_PASS_MARKER_MISSING')
        require(not base_gate['FAILED_GATES'] and not candidate_gate['FAIL_IDS'] and
                not base_gate['FAIL_IDS'], 'VERIFY_ZERO_WITH_FAILURE_DATA')
        return 'VERIFY_ALL_PASS'
    # No non-pytest gate has verifiable pytest node evidence; comparing names is not enough.
    permitted = {'unit_tests', 'webapp_tests'}
    failed = set(base_gate['FAILED_GATES'])
    require(failed and failed.issubset(permitted), 'VERIFY_NON_PYTEST_GATE_FAILED')
    # Combined pytest output cannot attribute node IDs to two failed gates safely.
    require(len(failed) == 1, 'VERIFY_NONZERO_WITHOUT_FAIL_IDS')
    # The strict parser intentionally excludes "FAILED gates (N): ..." summary lines.
    require(base_gate['FAIL_IDS'] and candidate_gate['FAIL_IDS'], 'VERIFY_NONZERO_WITHOUT_FAIL_IDS')
    for gate in failed:
        # Each failing pytest-backed gate needs at least one real pytest node ID.
        # Both named pytest gates emit identical pytest node syntax.
        require(any('.py::' in x for x in base_gate['FAIL_IDS']) and
                any('.py::' in x for x in candidate_gate['FAIL_IDS']),
                'VERIFY_NONZERO_WITHOUT_FAIL_IDS')
    extra = sorted(set(candidate_gate['FAIL_IDS']) - set(base_gate['FAIL_IDS']))
    require(not extra, 'VERIFY_NEW_FAILURE_IDS')
    return 'BASE_EQUIVALENT_NONZERO'


def verify_stage(repo, stage, result_dir, *, timeout):
    scripts='scripts/'
    def run(args, name, limit=timeout):
        rc,_=cmd([sys.executable,*args],repo,timeout=limit,log=result_dir/(stage+'-'+name+'.log'))
        return rc
    if stage=='generate':
        rc1=run([scripts+'fingerprint.py','--write'],'fingerprint')
        require(rc1==0,'GENERATE_FINGERPRINT_NONZERO')
        rc2=run([scripts+'execution_record.py','write','--repo-root',str(repo),'--plan-file',str(result_dir/'plan.json')],'execution_record')
        require(rc2==0,'GENERATE_RECORD_NONZERO')
        return {'GENERATED_SHA256':{p:sha_file(repo/p) for p in GENERATED}}
    if stage=='as_if':
        rc1=run([scripts+'check_consistency.py','--as-if-committed'],'consistency')
        rc2=run([scripts+'execution_record.py','verify','--as-if-committed'],'record_verify')
        require(rc1==0 and rc2==0,'AS_IF_NONZERO')
        return {'CHECKS':'PASS','EXECUTION_RECORD':'PASS'}
    if stage=='traceability':
        rc=run([scripts+'generate_rule_traceability.py','--check'],'traceability')
        require(rc==0,'TRACEABILITY_STALE')
        return {'TRACEABILITY':'PASS'}
    if stage=='check20':
        py=('import sys; sys.path.insert(0,"scripts"); import check_consistency as c; '
            'fails,infos=c._c20_column_failures("."); '
            'print(" ".join(infos)); sys.exit(1 if fails else 0)')
        rc=run(['-c',py],'check20')
        require(rc==0,'CHECK20_NONZERO')
        return {'CHECK20':'PASS'}
    raise DraftError('UNKNOWN_STAGE')


def _python_added_lines(base, candidate):
    """Actual added/replaced line numbers only; no historical unchanged-line lint."""
    before = base.splitlines(keepends=True)
    after = candidate.splitlines(keepends=True)
    changed = set()
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
        if tag in ('insert', 'replace'):
            changed.update(range(j1 + 1, j2 + 1))
    return changed


def lint_python_newlines(base_repo, candidate_repo, changed_paths):
    """AST-bound new/changed Python writes; dynamic newline/mode fail closed."""
    issues = []
    for rel in sorted(changed_paths):
        if not rel.endswith('.py'):
            continue
        target = candidate_repo / rel
        require(target.is_file(), 'NEWLINE_TARGET_MISSING')
        try:
            cand = target.read_text('utf-8')
            proc = subprocess.run(['git', '-C', str(base_repo), 'show', 'HEAD:' + rel],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
            if proc.returncode == 0:
                base = proc.stdout.decode('utf-8')
            else:
                require(not (base_repo / rel).exists(), 'NEWLINE_BASE_UNREADABLE')
                base = ''
            tree = ast.parse(cand, filename=rel)
        except (OSError, ValueError, UnicodeError, SyntaxError, subprocess.TimeoutExpired):
            raise DraftError('NEWLINE_AST_UNREADABLE') from None
        additions = _python_added_lines(base, cand)
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            if not any(i in additions for i in range(call.lineno, call.end_lineno + 1)):
                continue
            name = call.func.id if isinstance(call.func, ast.Name) else (
                call.func.attr if isinstance(call.func, ast.Attribute) else None)
            if name not in ('write_text', 'open'):
                continue
            kws = {kw.arg: kw.value for kw in call.keywords}
            newline = kws.get('newline')
            valid_newline = (isinstance(newline, ast.Constant) and newline.value in ('', '\n'))
            if name == 'write_text':
                if not valid_newline:
                    issues.append({'path': rel, 'line': call.lineno, 'kind': 'WRITE_TEXT_NEWLINE'})
                continue
            owner = call.func.value.id if (isinstance(call.func, ast.Attribute)
                                           and isinstance(call.func.value, ast.Name)) else None
            if owner == 'os':
                continue  # os.open(path, flags): file-descriptor API, no text mode or newline translation
            # builtins.open / io.open take mode SECOND; Path.open takes mode FIRST.
            offset = 1 if (isinstance(call.func, ast.Name) or owner == 'io') else 0
            mode = kws.get('mode', call.args[offset] if len(call.args) > offset else ast.Constant('r'))
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                m = mode.value
                if 'b' in m or not any(ch in m for ch in 'wax+'):
                    continue
            elif mode is None:
                continue
            else:
                issues.append({'path': rel, 'line': call.lineno, 'kind': 'DYNAMIC_TEXT_MODE'})
                continue
            if not valid_newline:
                issues.append({'path': rel, 'line': call.lineno, 'kind': 'TEXT_OPEN_NEWLINE'})
    return issues


def parse_junit_xml(path, rc, expected_paths):
    """Strict per-side pytest classification; ID = requested source path + class + parameterized test name."""
    require(rc in (0, 1) and path.is_file(), 'WINEMU_PYTEST_NONTEST_EXIT')
    try:
        root = ET.fromstring(path.read_bytes())
        suites = [root] if root.tag == 'testsuite' else (list(root) if root.tag == 'testsuites' else [])
        require(suites and all(x.tag == 'testsuite' for x in suites), 'WINEMU_XML_INVALID')
        counts = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
        cases = {}
        for suite in suites:
            for key in counts:
                v = int(suite.attrib[key])
                require(v >= 0, 'WINEMU_XML_INVALID')
                counts[key] += v
            for tc in suite:
                require(tc.tag == 'testcase', 'WINEMU_XML_INVALID')
                cname, name = tc.attrib['classname'], tc.attrib['name']
                matches = [p for p in expected_paths if cname == p[:-3].replace('/', '.') or
                           cname.startswith(p[:-3].replace('/', '.') + '.')]
                require(len(matches) == 1 and name, 'WINEMU_NODE_ID_UNMAPPED')
                pathrel = matches[0]
                prefix = pathrel[:-3].replace('/', '.')
                rest = cname[len(prefix):].lstrip('.')
                node_id = pathrel + ('::' + rest.replace('.', '::') if rest else '') + '::' + name
                require(node_id not in cases, 'WINEMU_NODE_ID_COLLISION')
                children = [x.tag for x in tc]
                require(all(t in ('failure','error','skipped','system-out','system-err') for t in children),
                        'WINEMU_XML_INVALID')
                status = next((x for x in ('failure', 'error', 'skipped') if x in children), 'passed')
                require(sum(x in children for x in ('failure', 'error', 'skipped')) <= 1,
                        'WINEMU_XML_INVALID')
                cases[node_id] = status
        require(counts['tests'] == len(cases) and counts['tests'] > 0 and
                counts['failures'] == list(cases.values()).count('failure') and
                counts['errors'] == list(cases.values()).count('error') and
                counts['skipped'] == list(cases.values()).count('skipped'), 'WINEMU_XML_COUNTS')
        failed = sorted(k for k, status in cases.items() if status in ('failure', 'error'))
        require((rc == 0 and not failed) or (rc == 1 and failed), 'WINEMU_XML_EXIT_MISMATCH')
        require(len(cases) > counts['skipped'], 'WINEMU_ALL_SKIPPED')
        return {'rc': rc, **counts, 'fail_ids': failed,
                'skipped_ids': sorted(k for k, v in cases.items() if v == 'skipped'),
                'executed_ids': sorted(k for k, v in cases.items() if v != 'skipped'),
                'junit_sha256': sha_file(path)}
    except (ET.ParseError, KeyError, TypeError, ValueError, UnicodeError, OSError):
        raise DraftError('WINEMU_XML_INVALID') from None


def focused_test_paths(args):
    """Reject selective pytest switches; no unknown options that could silently deselect tests."""
    paths = []
    for arg in args:
        require(isinstance(arg, str) and arg, 'WINEMU_FOCUSED_INVALID')
        if arg in ('-q', '-rs', '-ra', '-v', '-vv', '--tb=short'):
            continue
        require(not arg.startswith('-') and not arg.startswith('/') and not '\\' in arg,
                'WINEMU_FOCUSED_UNSAFE')
        rel = arg.split('::', 1)[0]
        require(rel.startswith('scripts/tests/') and rel.endswith('.py') and
                all(part not in ('', '.', '..') for part in rel.split('/')),
                'WINEMU_FOCUSED_UNSAFE')
        paths.append(rel)
    require(paths and len(paths) == len(set(paths)), 'WINEMU_FOCUSED_DUPLICATE')
    return paths


def winemu_stage(work, definition, prompt, plan, base, *, timeout):
    """Sixth stage: one canonical source, two isolated Windows-profile pytest runs."""
    d = json.loads(definition.read_bytes())
    pj = json.loads(plan.read_bytes())
    require(d.get('task_id') == pj.get('task_id') and d.get('base_oid') == base and
            d.get('kind') == 'production', 'WINEMU_DEFINITION_MISMATCH')
    lines = batch_runner.prompt_lines(prompt.read_bytes())
    spec = batch_runner.load_spec(lines, pj['task_id'])
    require(spec['kind'] == 'production' and spec['base_oid'] == base and
            spec['task_id'] == pj['task_id'], 'WINEMU_PROMPT_MISMATCH')
    expected = production_template.canonical_focused(d)
    require(expected == spec.get('focused') and isinstance(expected, dict), 'WINEMU_FOCUSED_DRIFT')
    args = expected['pytest_args']
    paths = focused_test_paths(args)
    changed_tests = {p for p in pj['allowed_paths'] if p.startswith('scripts/tests/') and p.endswith('.py')}
    require(changed_tests.issubset(paths), 'WINEMU_FOCUSED_INCOMPLETE')
    base_args = []
    excluded = []
    for arg in args:
        if arg.startswith('-'):
            base_args.append(arg)
            continue
        rel = arg.split('::', 1)[0]
        in_base = (work/'baseclone'/rel).is_file()
        in_cand = (work/'candclone'/rel).is_file()
        require(in_cand, 'WINEMU_CAND_TARGET_MISSING')
        if in_base:
            base_args.append(arg)
            continue
        # Plan has no new-path field: compare three independent facts.
        new_spec = d.get('new_files') or {}
        require(rel in new_spec and rel in changed_tests and
                spec['authors'].get(rel,{}).get('source',{}).get('kind') == 'block' and
                rel in pj['required_paths'], 'WINEMU_UNAUTHORIZED_NEW_PATH')
        excluded.append(rel)
    require(set(paths) and set(paths) == set(focused_test_paths(args)), 'WINEMU_TARGET_DRIFT')
    details = {'GIT_PROFILE': 'windows', 'EMULATION_SCOPE':
        'Path.write_text CRLF; builtins.open text-write CRLF; Path.symlink_to winerror 1314; '
        'NOT os.symlink/os.mkfifo/os.name; NOT Windows native D-10',
        'DEFINITION_SHA256': sha_file(definition), 'PROMPT_SHA256': sha_file(prompt),
        'PYTEST_ARGS': args, 'BASE_ARGS': base_args, 'BASE_EXCLUDED_NEW_FILES': sorted(set(excluded))}
    for label, node_args in (('BASE', base_args), ('CANDIDATE', args)):
        if label == 'BASE' and not any(not a.startswith('-') for a in node_args):
            require(excluded and set(excluded) == set(paths), 'WINEMU_UNAUTHORIZED_EMPTY_BASE')
            details['BASE_SELECTION'] = 'AUTHORIZED_EMPTY_NEW_FILES_ONLY'
            details['BASE'] = {'rc': None, 'tests': 0, 'fail_ids': [], 'junit_sha256': None}
            continue
        clone = work / ('baseclone' if label == 'BASE' else 'candclone')
        junit = work / ('winemu-' + label.lower() + '.xml')
        log = work / ('winemu_base_diff-' + label.lower() + '.log')
        started = time.monotonic()
        try:
            rc, out = batch_sim.winemu_collect(str(clone), node_args, str(junit), timeout=timeout)
        except batch_sim.SimError:
            raise DraftError('WINEMU_PROFILE_FAILED') from None
        log.write_bytes(out)
        parsed = parse_junit_xml(junit, rc, sorted(set(paths)-set(excluded) if label == 'BASE' else paths))
        parsed['elapsed_sec'] = round(time.monotonic()-started,3)
        parsed['log_sha256'] = sha_file(log)
        details[label] = parsed
    executed = details['CANDIDATE']['executed_ids']
    require(all(any(node.startswith(rel + '::') for node in executed) for rel in changed_tests),
            'WINEMU_CHANGED_FILE_NOT_EXECUTED')
    base_fail = set(details['BASE']['fail_ids'])
    cand_fail = set(details['CANDIDATE']['fail_ids'])
    details['EXTRA_FAIL_IDS'] = sorted(cand_fail-base_fail)
    require(not details['EXTRA_FAIL_IDS'], 'WINEMU_EXTRA_FAILURE_IDS')
    # W1 real coverage: unchanged historical CRLF regression cases must execute when their file is selected.
    return {'STATUS': 'PASS', **details}


def execute(ns):
    source=Path(ns.source).resolve(); patch=Path(ns.patch).resolve(); plan=Path(ns.plan).resolve(); work=Path(ns.workdir).resolve()
    definition=Path(ns.definition).resolve() if ns.definition else None
    prompt=Path(ns.prompt).resolve() if ns.prompt else None
    require(source.is_dir() and (source/'.git').exists() and patch.is_file() and plan.is_file(), 'INPUT_MISSING')
    # Production sources must supply both bound canonical files. Minimal unit fixtures are isolated below.
    synthetic = not (source/'scripts'/'batch_sim.py').is_file()
    require(synthetic or (definition is not None and prompt is not None and definition.is_file() and prompt.is_file()),
            'WINEMU_BINDING_REQUIRED')
    require(not any(source == p or source in p.parents for p in (patch,plan,work)), 'SOURCE_OVERLAP')
    require(not (work == source or work in source.parents or source in work.parents), 'WORKDIR_OVERLAP')
    base=git(source,'rev-parse','HEAD')
    require(HEX40.fullmatch(base) is not None, 'BASE_OID_INVALID')
    require(git(source,'rev-parse','--is-shallow-repository')=='false','SHALLOW_BASE')
    require(not git(source,'status','--porcelain=v1','--untracked-files=all'),'BASE_DIRTY')
    pj=json.loads(plan.read_bytes())
    allowed=validate_plan(pj,base)
    require(patch.stat().st_size <= 20*1024*1024, 'PATCH_OVERSIZED')
    hashes=fingerprint(source,patch,plan,Path(__file__).resolve().parent,work,definition=definition,prompt=prompt)
    journal=work/'draft-state.json'
    if ns.resume:
        require(journal.is_file(),'RESUME_STATE_MISSING')
        state=json.loads(journal.read_bytes())
        require(state.get('HASHES')==hashes,'RESUME_FINGERPRINT_CHANGED_NEW_WORKDIR_REQUIRED')
        require([e['stage'] for e in state['completed']]==list(STAGES[:len(state['completed'])]),'RESUME_STATE_ORDER')
        require((work/'candclone'/'.git').exists(),'RESUME_CLONE_MISSING')
        assert_baseclone(work/'baseclone', base, state.get('BASECLONE_TREE_OID'))
        require(candidate_digest(work) == state.get('CANDIDATE_DIFF_SHA256'), 'RESUME_CANDIDATE_DRIFT')
        require(sha_file(work/'plan.json')==hashes['PLAN_SHA256'],'RESUME_PLAN_DRIFT')
        for p,digest in state.get('GENERATED_SHA256',{}).items():
            require(sha_file(work/'candclone'/p)==digest,'RESUME_GENERATED_DRIFT')
        for info in state['completed']:
            for log_name,digest in info.get('LOGS',{}).items():
                require(sha_file(work/log_name)==digest,'RESUME_LOG_DRIFT')
    else:
        require(not work.exists() or (work.is_dir() and not any(work.iterdir())), 'WORKDIR_NOT_EMPTY')
        work.mkdir(parents=True,exist_ok=True)
        # Clone names have identical length (9 chars) to preserve long-path test parity.
        # --no-local ensures objects are not shared; --template= avoids external hooks.
        env={k:v for k,v in os.environ.items() if not k.upper().startswith('GIT_')}
        env['GIT_CONFIG_NOSYSTEM']='1'
        (work/'gitconfig').write_bytes(b'')
        env['GIT_CONFIG_GLOBAL']=str(work/'gitconfig')
        for name in ('baseclone','candclone'):
            rc,_=cmd(['git','clone','-q','--no-local','--template=',str(source),str(work/name)],work,timeout=300,env=env)
            require(rc==0,'CLONE_NONZERO')
            require(git(work/name,'rev-parse','HEAD')==base,'CLONE_HEAD_DRIFT')
        (work/'plan.json').write_bytes(plan.read_bytes())
        assert_baseclone(work/'baseclone', base)
        rc,_=cmd(['git','-C',str(work/'candclone'),'apply','--check',str(patch)],work)
        require(rc==0,'PATCH_INVALID')
        rc,_=cmd(['git','-C',str(work/'candclone'),'apply',str(patch)],work)
        require(rc==0,'PATCH_NONZERO')
        bad=lint_added_sha_labels(patch.read_bytes())
        require(not bad,'SHA_FORMAT_LINT_FAILED')
        changes=set(git(work/'candclone','diff','--name-only').splitlines())
        changes.update(git(work/'candclone','ls-files','--others','--exclude-standard').splitlines())
        require(changes.issubset(allowed) and changes and set(pj['required_paths'])-set(GENERATED)<=changes,'AUTHOR_SCOPE_MISMATCH')
        require(not lint_python_newlines(work/'baseclone',work/'candclone',changes), 'NEWLINE_DIFF_LINT_FAILED')
        state={'schema_version':1,'HASHES':hashes,'completed':[],'GENERATED_SHA256':{},
               'CANDIDATE_DIFF_SHA256':candidate_digest(work),
               'BASECLONE_TREE_OID':git(work/'baseclone','rev-parse','HEAD^{tree}')}
        atomic_json(journal,state)
    result_dir=work
    for stage in STAGES[len(state['completed']):]:
        if stage=='base_diff_verify_all':
            assert_baseclone(work/'baseclone', base, state.get('BASECLONE_TREE_OID'))
            logs={}
            codes={}
            for name in ('baseclone','candclone'):
                logfile=work/(stage+'-'+name+'.log')
                rc,_=cmd([sys.executable,'scripts/verify_all.py'],work/name,timeout=ns.timeout,log=logfile)
                codes[name]=rc;logs[name]=parse_gate(logfile)
            outcome=classify_base_candidate(codes['baseclone'],codes['candclone'],logs['baseclone'],logs['candclone'])
            extra=sorted(set(logs['candclone']['FAIL_IDS'])-set(logs['baseclone']['FAIL_IDS']))
            details={'STATUS':outcome,'BASE_RC':codes['baseclone'],'CAND_RC':codes['candclone'],
                     'BASE_FAIL_IDS':logs['baseclone']['FAIL_IDS'],'CANDIDATE_FAIL_IDS':logs['candclone']['FAIL_IDS'],
                     'EXTRA_FAIL_IDS':extra,'BASE_FAILED_GATES':logs['baseclone']['FAILED_GATES'],
                     'CANDIDATE_FAILED_GATES':logs['candclone']['FAILED_GATES'],'BASE_LOG_SHA256':logs['baseclone']['LOG_SHA256'],
                     'CANDIDATE_LOG_SHA256':logs['candclone']['LOG_SHA256']}
        elif stage=='winemu_base_diff':
            if synthetic:
                details={'STATUS':'SYNTHETIC_MINI_REPO_ONLY'}  # Unit fixture, never a production clone.
            else:
                details=winemu_stage(work,definition,prompt,plan,base,timeout=ns.timeout)
        else:
            details=verify_stage(work/'candclone',stage,result_dir,timeout=ns.timeout)
        if stage=='generate':
            state['GENERATED_SHA256']=details['GENERATED_SHA256']
        state['CANDIDATE_DIFF_SHA256']=candidate_digest(work)
        written={p.name:sha_file(p) for p in sorted(work.glob(stage+'-*.log'))}
        state['completed'].append({'stage':stage,'details':details,'LOGS':written})
        atomic_json(journal,state)
        print('DRAFT_PRECHECK STEP '+stage+' '+details.get('STATUS','PASS'),flush=True)
    require(state['completed'][-1]['details']['STATUS'] in ('PASS','SYNTHETIC_MINI_REPO_ONLY'),
            'WINEMU_STAGE_NOT_PASS')
    state['STAGE6']='SYNTHETIC' if synthetic else 'REAL'
    state['overall']='SIX_STEPS_PASS' if state['completed'][2]['details']['STATUS']=='VERIFY_ALL_PASS' else 'BASE_EQUIVALENT_NONZERO'
    atomic_json(journal,state)
    require(git(source,'rev-parse','HEAD')==base and not git(source,'status','--porcelain=v1','--untracked-files=all'), 'SOURCE_MODIFIED')
    final=work/'draft-result.json'
    atomic_json(final,state)
    print('DRAFT_PRECHECK RESULT '+state['overall'])
    for key in ('BASE_OID','AUTHOR_SHA256','PLAN_SHA256','TOOL_SHA256','ENV_SHA256','CACHE_KEY_SHA256'):
        print(key+'='+hashes[key])
    print('RESULT_JSON_SHA256='+sha_file(final))
    return 0

def main(argv=None):
    p=argparse.ArgumentParser(description='Q2 five-step auditor-only draft precheck; never commits or pushes')
    p.add_argument('--source',required=True)
    p.add_argument('--patch',required=True)
    p.add_argument('--plan',required=True)
    p.add_argument('--workdir',required=True)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--definition')
    p.add_argument('--prompt')
    p.add_argument('--timeout',type=int,default=1800)
    args=p.parse_args(argv)
    try:
        return execute(args)
    except (DraftError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as e:
        print('DRAFT_PRECHECK FAIL '+(str(e) if isinstance(e,DraftError) else type(e).__name__))
        return 1

if __name__=='__main__':
    sys.exit(main())
