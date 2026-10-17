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

STAGES = ('generate', 'as_if', 'base_diff_verify_all', 'traceability', 'check20')
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

def fingerprint(source, patch, plan, scripts_dir, workspace):
    tools = [scripts_dir / name for name in ('draft_precheck.py','check_consistency.py',
             'execution_record.py','fingerprint.py','verify_all.py','generate_rule_traceability.py','impact_scan.py')]
    tool_h=sha(json.dumps({p.name:sha_file(p) for p in tools},sort_keys=True).encode('utf8'))
    env_data={'os':platform.platform(),'python':sys.version, 'python_executable':sys.executable,
              'uid':getattr(os,'getuid',lambda:None)(), 'cwd_path_bytes':len(str(workspace).encode()),
              'git': cmd(['git','--version'],source)[1].decode('utf-8','replace').strip(),
              'node': cmd(['node','--version'],source)[1].decode('utf-8','replace').strip()}
    env_h=sha(json.dumps(env_data,sort_keys=True).encode('utf8'))
    hashes={'BASE_OID':git(source,'rev-parse','HEAD'), 'AUTHOR_SHA256':sha_file(patch),
            'PLAN_SHA256':sha_file(plan),'TOOL_SHA256':tool_h,'ENV_SHA256':env_h}
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

def execute(ns):
    source=Path(ns.source).resolve(); patch=Path(ns.patch).resolve(); plan=Path(ns.plan).resolve(); work=Path(ns.workdir).resolve()
    require(source.is_dir() and (source/'.git').exists() and patch.is_file() and plan.is_file(), 'INPUT_MISSING')
    require(not any(source == p or source in p.parents for p in (patch,plan,work)), 'SOURCE_OVERLAP')
    require(not (work == source or work in source.parents or source in work.parents), 'WORKDIR_OVERLAP')
    base=git(source,'rev-parse','HEAD')
    require(HEX40.fullmatch(base) is not None, 'BASE_OID_INVALID')
    require(git(source,'rev-parse','--is-shallow-repository')=='false','SHALLOW_BASE')
    require(not git(source,'status','--porcelain=v1','--untracked-files=all'),'BASE_DIRTY')
    pj=json.loads(plan.read_bytes())
    allowed=validate_plan(pj,base)
    require(patch.stat().st_size <= 20*1024*1024, 'PATCH_OVERSIZED')
    hashes=fingerprint(source,patch,plan,Path(__file__).resolve().parent,work)
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
        else:
            details=verify_stage(work/'candclone',stage,result_dir,timeout=ns.timeout)
        if stage=='generate':
            state['GENERATED_SHA256']=details['GENERATED_SHA256']
        state['CANDIDATE_DIFF_SHA256']=candidate_digest(work)
        written={p.name:sha_file(p) for p in sorted(work.glob(stage+'-*.log'))}
        state['completed'].append({'stage':stage,'details':details,'LOGS':written})
        atomic_json(journal,state)
        print('DRAFT_PRECHECK STEP '+stage+' '+details.get('STATUS','PASS'),flush=True)
    state['overall']='FIVE_STEPS_PASS' if state['completed'][2]['details']['STATUS']=='VERIFY_ALL_PASS' else 'BASE_EQUIVALENT_NONZERO'
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
    p.add_argument('--timeout',type=int,default=1800)
    args=p.parse_args(argv)
    try:
        return execute(args)
    except (DraftError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as e:
        print('DRAFT_PRECHECK FAIL '+(str(e) if isinstance(e,DraftError) else type(e).__name__))
        return 1

if __name__=='__main__':
    sys.exit(main())
