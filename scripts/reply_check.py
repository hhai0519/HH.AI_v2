#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/reply_check.py
Macro-side check of an Executor reply against the delivered prompt (B-119 G1 Q1).

  python scripts/reply_check.py --prompt <TASK_ID>-prompt.txt --reply <reply text file> [--capture <s1 zip>]

The prompt binds the task, kind, Base, branch, candidate, prompt SHA-256 and the exact step list
(batch_runner.load_spec and derive_steps). Only runner output lines are read; every other line (the Executor's
prose) is ignored. A line that starts with a runner prefix must match its exact format (REPLY_LINE_MALFORMED), every
commit SHA must be 40 lowercase hex characters and every file SHA-256 64 (REPLY_SHA_INVALID).

Every outcome has a fixed line set: each runner line kind has a required count range, and any other runner line is
REPLY_LINE_NOT_EXPECTED; a missing or repeated line fails with REPLY_<LINE>_MISSING / _REPEATED.
  production success  CI_RUN candidate (bound branch, head = COMMIT), "COMMIT <sha> | CI PASS | S1 NONE"; when the
                      prompt has a bundle step either the READY block (BUNDLE_FILE named after Base and candidate,
                      ORIGIN_MAIN = Base, HANDOFF_TO_AUDITOR, HANDOFF_CARD_SHA256 = SHA-256 of HANDOFF_CARD_JSON, every
                      card field equal to the lines above) or one BUNDLE FAILED <code>; TIMING; STATE done = every
                      step, halted=None, bundle as reported; optional STEP_PASS and BOUNDED_EXIT ... code=0 lines.
  promotion success   CI_RUN candidate and postmain for the candidate, "MAIN <sha> | POST-MAIN CI PASS | S1 NONE",
                      optional MAIN_PROMOTED <candidate>, TIMING, STATE as above.
  A "CI PENDING" COMMIT or MAIN line fails (REPLY_CI_PENDING): the reply does not prove a passing CI run.
  S1 inside a step    (STATE halted = <step>:<code>, done = the steps before it) one S1 line, at most one S1_DETAIL,
                      exactly one metadata form (S1_EVIDENCE_FILE + S1_SHA256SUMS_FILE + S1_EVIDENCE_JSON bound to the
                      task, step and code, or S1_EVIDENCE_STATUS=UNAVAILABLE), exactly one capture form
                      (S1_FULL_CAPTURE_FILE + _CARD + _JSON, or S1_FULL_CAPTURE_STATUS=<status>), BOUNDED lines only
                      for stages up to the stopped one (earlier stages code=0), TIMING, STATE.
  S1 before a step    (runner stopped before control was written or before the step ran: STATE halted=None, done a
                      prefix of the steps) only for the runner's pre-execution codes: START_STATE_MISMATCH,
                      SHALLOW_CLONE, START_REMOTE_QUERY_INVALID, ORIGIN_MAIN_DRIFT, ARTIFACT_PATH_GUARD_FAILED and
                      ARTIFACT_ALREADY_EXISTS at preflight with nothing done; CONTROL_MISSING with nothing done;
                      CONTROL_INVALID, CONTROL_BINDING_DRIFT, STEP_ORDER_VIOLATION, UNKNOWN_STEP,
                      WORKING_DIRECTORY_MISMATCH, PROMPT_UNREADABLE and SPEC_* at any point; no metadata, capture or
                      BOUNDED line. Any other S1 with halted=None fails (REPLY_STATE_MISMATCH).
  An S1 code is upper case, or UNEXPECTED_<Python exception name> as the runner prints it.
TIMING must be self-consistent: end >= start, elapsed_sec within 0.06 s of end - start, elapsed_min its whole
minutes.

Evidence (證據 log 非空), only for an S1 inside a bounded step (focused, precommit, stage, postcommit). The bounded
run is STARTED when the code can only occur after it (see STAGES) or the reply has a BOUNDED line for the stage,
NOT_STARTED only when the code can only occur before it, otherwise UNKNOWN; the runner metadata says whether the
record exists:
  STARTED and listed non-empty      TEXT_ATTESTED: NOT_VERIFIED until --capture verifies it, then PASS
  STARTED and not listed or empty   INCOMPLETE (FAIL)
  NOT_STARTED and not listed        N/A
  UNKNOWN and listed non-empty      NOT_VERIFIED, or PASS once --capture verifies the record
  any other case, or no metadata    NOT_VERIFIED (never N/A)
--capture verifies the S1 full-capture ZIP: its SHA-256 equals S1_FULL_CAPTURE_FILE, the card (hash-bound to
S1_FULL_CAPTURE_CARD) names this task, step, code, Base and archive, the manifest covers every member, the prompt
member equals the bound prompt SHA-256, the control member names this task, prompt and halted step, the metadata
and its SHA256SUMS members equal the reply lines, and every metadata entry (the bounded record included) matches.
An S1 outside a bounded step, an S1 before a step and every success reply have evidence N/A; --capture is refused
there (CAPTURE_NOT_EXPECTED).

Output: REPLY_CHECK lines with fixed codes only (never reply content). Exit 0 = PASS, 2 = NOT_VERIFIED (fields
complete, evidence still needs the actual files), 1 = FAIL.
"""

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import batch_runner  # noqa: E402 - spec parser and step list are the reference
    import prompt_builder  # noqa: E402 - prompt name and task binding
finally:
    sys.path.pop(0)

OID = re.compile(r'^[0-9a-f]{40}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
CODE = r'(?:[A-Z][A-Z0-9_]*|UNEXPECTED_[A-Za-z_][A-Za-z0-9_]*)'
NEXT_STEP = 'USER_FORWARD_BUNDLE_AND_HANDOFF_CARD_TO_ACTIVE_AUDITOR_FOR_INDEPENDENT_REVIEW'

# Bounded steps: (stage, codes raised only before the bounded run, codes raised only after it started).
# Taken from batch_runner Batch.step_focused/step_precommit/step_stage/step_postcommit, bounded() and gate();
# a code raised both before and after (expect_scope, verify_hashes on both sides) is in neither set.
STAGES = {
    'focused': ('FOCUSED', {'ARTIFACT_PATH_GUARD_FAILED'}, {'FOCUSED_TIMEOUT', 'FOCUSED_NONZERO'}),
    'precommit': ('PRECOMMIT', {'ARTIFACT_PATH_GUARD_FAILED'},
                  {'PRECOMMIT_TIMEOUT', 'PRECOMMIT_NONZERO', 'PRECOMMIT_COMPLETION_UNPROVEN', 'PRECOMMIT_AUTHOR_DRIFT'}),
    'stage': ('STAGED', {'STAGE_HEAD_DRIFT', 'STAGE_SCOPE_MISMATCH', 'STAGE_SCOPE_DRIFT', 'STAGE_AUTHOR_DRIFT',
                         'STAGE_FAILED', 'STAGED_SET_MISMATCH', 'UNSTAGED_OR_UNTRACKED_PRESENT',
                         'STAGED_AUTHOR_MISMATCH', 'ARTIFACT_PATH_GUARD_FAILED'},
              {'STAGED_TIMEOUT', 'STAGED_NONZERO', 'STAGED_COMPLETION_UNPROVEN', 'STAGED_SET_DRIFT',
               'STAGED_AUTHOR_DRIFT'}),
    'postcommit': ('POSTCOMMIT', {'POSTCOMMIT_PARENT_DRIFT', 'ARTIFACT_PATH_GUARD_FAILED'},
                   {'POSTCOMMIT_TIMEOUT', 'POSTCOMMIT_NONZERO', 'POSTCOMMIT_COMPLETION_UNPROVEN',
                    'POSTCOMMIT_HEAD_DRIFT', 'POSTCOMMIT_DIRTY'}),
}
# Halts reported before the step body runs (control not written, or not updated): STATE keeps halted=None.
PRECONTROL = {'START_STATE_MISMATCH', 'SHALLOW_CLONE', 'START_REMOTE_QUERY_INVALID', 'ORIGIN_MAIN_DRIFT',
              'ARTIFACT_PATH_GUARD_FAILED', 'ARTIFACT_ALREADY_EXISTS'}
BEFORE_STEP = {'CONTROL_INVALID', 'CONTROL_BINDING_DRIFT', 'STEP_ORDER_VIOLATION', 'UNKNOWN_STEP',
               'WORKING_DIRECTORY_MISMATCH', 'PROMPT_UNREADABLE'}

# name -> (prefix, exact format, positions of commit SHAs, positions of file SHA-256)
FORMATS = [
    ('CI_RUN', 'CI_RUN ', r'^CI_RUN phase=(candidate|postmain) run_id=([1-9][0-9]*) attempt=([1-9][0-9]*) '
                          r'event=push branch=(\S+) head_sha=(\S+) verify=success gateway-windows=success$', (5,), ()),
    ('COMMIT', 'COMMIT ', r'^COMMIT (\S+) \| CI (PASS|PENDING) \| S1 NONE$', (1,), ()),
    ('MAIN_PROMOTED', 'MAIN_PROMOTED ', r'^MAIN_PROMOTED (\S+)$', (1,), ()),
    ('MAIN', 'MAIN ', r'^MAIN (\S+) \| POST-MAIN CI (PASS|PENDING) \| S1 NONE$', (1,), ()),
    ('BUNDLE_FILE', 'BUNDLE_FILE=', r'^BUNDLE_FILE=(.+)$', (), ()),
    ('BUNDLE_FAILED', 'BUNDLE FAILED ', r'^BUNDLE FAILED ([A-Z][A-Z0-9_]*)$', (), ()),
    ('ORIGIN_MAIN', 'ORIGIN_MAIN=', r'^ORIGIN_MAIN=(\S+)$', (1,), ()),
    ('HANDOFF_TO_AUDITOR', 'HANDOFF_TO_AUDITOR=', r'^HANDOFF_TO_AUDITOR=(\S+)$', (), ()),
    ('HANDOFF_CARD_SHA256', 'HANDOFF_CARD_SHA256=', r'^HANDOFF_CARD_SHA256=(\S+)$', (), (1,)),
    ('HANDOFF_CARD_JSON', 'HANDOFF_CARD_JSON=', r'^HANDOFF_CARD_JSON=(\{.*\})$', (), ()),
    ('TIMING', 'TIMING ', r'^TIMING start=(\S+) end=(\S+) elapsed_sec=([0-9]+(?:\.[0-9])?) elapsed_min=([0-9]+)$', (), ()),
    ('STATE', 'STATE ', r'^STATE done=([a-z0-9,]*) halted=(\S+?)(?: bundle=([A-Z][A-Z0-9_]*))?$', (), ()),
    ('STEP_PASS', 'STEP_PASS ', r'^STEP_PASS ([a-z0-9]+)$', (), ()),
    ('S1_DETAIL', 'S1_DETAIL ', r'^S1_DETAIL (.+)$', (), ()),
    ('S1_EVIDENCE_FILE', 'S1_EVIDENCE_FILE=', r'^S1_EVIDENCE_FILE=(\S+) sha256=(\S+)$', (), (2,)),
    ('S1_SHA256SUMS_FILE', 'S1_SHA256SUMS_FILE=', r'^S1_SHA256SUMS_FILE=(\S+) sha256=(\S+)$', (), (2,)),
    ('S1_EVIDENCE_JSON', 'S1_EVIDENCE_JSON=', r'^S1_EVIDENCE_JSON=(\{.*\})$', (), ()),
    ('S1_EVIDENCE_STATUS', 'S1_EVIDENCE_STATUS=', r'^S1_EVIDENCE_STATUS=(UNAVAILABLE)$', (), ()),
    ('S1_FULL_CAPTURE_FILE', 'S1_FULL_CAPTURE_FILE=', r'^S1_FULL_CAPTURE_FILE=(\S+) sha256=(\S+)$', (), (2,)),
    ('S1_FULL_CAPTURE_CARD', 'S1_FULL_CAPTURE_CARD=', r'^S1_FULL_CAPTURE_CARD=(\S+) sha256=(\S+)$', (), (2,)),
    ('S1_FULL_CAPTURE_JSON', 'S1_FULL_CAPTURE_JSON=', r'^S1_FULL_CAPTURE_JSON=(\{.*\})$', (), ()),
    ('S1_FULL_CAPTURE_STATUS', 'S1_FULL_CAPTURE_STATUS=', r'^S1_FULL_CAPTURE_STATUS=([A-Z][A-Z_]*)$', (), ()),
    ('S1', 'S1 ', r'^S1 (' + CODE + r')(?: \| step ([a-z0-9]+)| ([a-z0-9]+):(' + CODE + r'))?$', (), ()),
    ('BOUNDED_EXIT', 'BOUNDED_EXIT ', r'^BOUNDED_EXIT ([A-Z]+) code=(-?[0-9]+) \| .*$', (), ()),
    ('BOUNDED_TIMEOUT', 'BOUNDED_TIMEOUT ', r'^BOUNDED_TIMEOUT ([A-Z]+) limit=[0-9]+s kill=\S+$', (), ()),
]
COMPILED = [(n, p, re.compile(f), o, s) for n, p, f, o, s in FORMATS]
METADATA = ('S1_EVIDENCE_FILE', 'S1_SHA256SUMS_FILE', 'S1_EVIDENCE_JSON')
CAPTURE = ('S1_FULL_CAPTURE_FILE', 'S1_FULL_CAPTURE_CARD', 'S1_FULL_CAPTURE_JSON')
READY = ('BUNDLE_FILE', 'ORIGIN_MAIN', 'HANDOFF_TO_AUDITOR', 'HANDOFF_CARD_SHA256', 'HANDOFF_CARD_JSON')


class CheckError(Exception):
    """Fixed failure code; never carries reply content."""


def _require(cond, code):
    if not cond:
        raise CheckError(code)


def _json(text, code):
    """Strict JSON object: duplicate keys, NaN and Infinity fail."""
    def pairs(items):
        keys = [k for k, _ in items]
        _require(len(keys) == len(set(keys)), code)
        return dict(items)

    def constant(_name):
        raise CheckError(code)
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except ValueError:
        raise CheckError(code)
    _require(isinstance(value, dict), code)
    return value


def parse_lines(text):
    """{name: [match, ...]} for runner lines (CI_RUN split by phase); prose is ignored."""
    _require('\r' not in text, 'REPLY_CR')
    found = {n: [] for n, *_ in FORMATS}
    found.update({'CI_RUN_CANDIDATE': [], 'CI_RUN_POSTMAIN': []})
    for raw in text.split('\n'):
        line = raw.strip()
        for name, prefix, fmt, oids, shas in COMPILED:
            if line.startswith(prefix) or line == prefix.strip():
                m = fmt.match(line)
                _require(m is not None, 'REPLY_LINE_MALFORMED')
                for i in oids:
                    _require(OID.match(m.group(i)) is not None, 'REPLY_SHA_INVALID')
                for i in shas:
                    _require(SHA256.match(m.group(i)) is not None, 'REPLY_SHA_INVALID')
                found[name].append(m)
                if name == 'CI_RUN':
                    found['CI_RUN_' + m.group(1).upper()].append(m)
                break
    del found['CI_RUN']
    return found


def cardinality(found, ranges):
    """Every runner line kind within its (min, max); kinds not listed must be absent."""
    for name, items in found.items():
        lo, hi = ranges.get(name, (0, 0))
        if len(items) < lo:
            raise CheckError('REPLY_' + name + '_MISSING')
        if len(items) > hi:
            raise CheckError(('REPLY_' + name + '_REPEATED') if hi else 'REPLY_LINE_NOT_EXPECTED')


def one(found, name):
    return found[name][0]


def check_timing(found):
    m = one(found, 'TIMING')
    try:
        start, end = datetime.fromisoformat(m.group(1)), datetime.fromisoformat(m.group(2))
        delta = (end - start).total_seconds()
    except (ValueError, TypeError):
        raise CheckError('REPLY_TIMING_INVALID')
    _require(start.tzinfo is not None and end.tzinfo is not None and delta >= 0, 'REPLY_TIMING_INVALID')
    _require(abs(delta - float(m.group(3))) <= 0.06 and int(m.group(4)) == int(delta // 60), 'REPLY_TIMING_INCONSISTENT')


def check_ci(found, phase, branch, head):
    for m in found['CI_RUN_' + phase.upper()]:
        _require(m.group(4) == branch and m.group(5) == head, 'REPLY_CI_RUN_' + phase.upper() + '_MISMATCH')


def state(found):
    m = one(found, 'STATE')
    return (m.group(1).split(',') if m.group(1) else []), m.group(2), m.group(3)


def check_step_pass(found, done):
    passed = [m.group(1) for m in found['STEP_PASS']]
    _require(len(passed) == len(set(passed)) and set(passed) <= set(done), 'REPLY_STEP_PASS_MISMATCH')


def check_bounded_lines(found, steps, stopped=None):
    """BOUNDED lines: at most one per stage; a stage before the stopped step (every stage of the prompt on success)
    only with BOUNDED_EXIT code=0; the stopped step's own stage with any result; no other stage."""
    earlier = steps if stopped is None else steps[:steps.index(stopped)]
    allowed = [STAGES[s][0] for s in earlier if s in STAGES]
    last = STAGES[stopped][0] if stopped in STAGES else None
    seen = set()
    for name in ('BOUNDED_EXIT', 'BOUNDED_TIMEOUT'):
        for m in found[name]:
            stage = m.group(1)
            _require(stage not in seen and (stage == last or (stage in allowed and name == 'BOUNDED_EXIT'
                                                              and m.group(2) == '0')), 'REPLY_BOUNDED_MISMATCH')
            seen.add(stage)


def check_bundle(found, task, spec, head):
    base = spec['base_oid']
    if found['BUNDLE_FAILED']:
        return 'FAILED_' + one(found, 'BUNDLE_FAILED').group(1)
    bfile = one(found, 'BUNDLE_FILE').group(1)
    _require(re.search(r'HH\.AI_v2-[0-9]{8}-[0-9]{6}-' + base[:7] + '-' + head[:7] + r'\.bundle$', bfile) is not None,
             'REPLY_BUNDLE_NAME_MISMATCH')
    _require(one(found, 'ORIGIN_MAIN').group(1) == base, 'REPLY_ORIGIN_MAIN_MISMATCH')
    _require(one(found, 'HANDOFF_TO_AUDITOR').group(1) == '.git/' + task + '-handoff.json', 'REPLY_HANDOFF_MISMATCH')
    raw = one(found, 'HANDOFF_CARD_JSON').group(1)
    _require(hashlib.sha256(raw.encode('utf-8')).hexdigest() == one(found, 'HANDOFF_CARD_SHA256').group(1),
             'REPLY_HANDOFF_SHA_MISMATCH')
    card = _json(raw, 'REPLY_HANDOFF_JSON_INVALID')
    ci = one(found, 'CI_RUN_CANDIDATE')
    expected = {'schema_version': 1, 'phase': 'candidate', 'task_id': task, 'base_oid': base, 'candidate_oid': head,
                'branch': spec['branch'], 'candidate_ci': {'status': 'PASS', 'run_id': int(ci.group(2)),
                                                           'attempt': int(ci.group(3)), 'head_sha': head},
                'postmain': 'NOT_RUN', 'bundle_status': 'READY', 'bundle_file': bfile, 'next_step': NEXT_STEP}
    _require(card == expected, 'REPLY_HANDOFF_CARD_MISMATCH')
    return 'READY'


def check_success(found, task, spec, steps):
    ranges = {'TIMING': (1, 1), 'STATE': (1, 1), 'STEP_PASS': (0, len(steps)), 'CI_RUN_CANDIDATE': (1, 1)}
    if spec['kind'] == 'production':
        ranges.update({'COMMIT': (1, 1), 'BOUNDED_EXIT': (0, len(STAGES))})
        if 'bundle' in steps:
            ranges.update({'BUNDLE_FAILED': (1, 1)} if found['BUNDLE_FAILED'] else {n: (1, 1) for n in READY})
    else:
        ranges.update({'MAIN': (1, 1), 'MAIN_PROMOTED': (0, 1), 'CI_RUN_POSTMAIN': (1, 1)})
    cardinality(found, ranges)
    if spec['kind'] == 'production':
        m = one(found, 'COMMIT')
        head = m.group(1)
        check_ci(found, 'candidate', spec['branch'], head)
        bundle = check_bundle(found, task, spec, head) if 'bundle' in steps else None
        check_bounded_lines(found, steps)
        outcome = 'COMMIT'
    else:
        head = spec['candidate_oid']
        m = one(found, 'MAIN')
        _require(m.group(1) == head, 'REPLY_MAIN_MISMATCH')
        for p in found['MAIN_PROMOTED']:
            _require(p.group(1) == head, 'REPLY_MAIN_MISMATCH')
        check_ci(found, 'candidate', spec['candidate_branch'], head)
        check_ci(found, 'postmain', 'main', head)
        bundle = None
        outcome = 'MAIN'
    _require(m.group(2) == 'PASS', 'REPLY_CI_PENDING')
    check_timing(found)
    done, halted, state_bundle = state(found)
    _require(done == steps and halted == 'None', 'REPLY_STATE_MISMATCH')
    _require(state_bundle == bundle, 'REPLY_STATE_BUNDLE_MISMATCH')
    check_step_pass(found, done)
    return outcome + ' ' + head


def s1_line(found):
    m = one(found, 'S1')
    if m.group(1) == 'TASK_ALREADY_HALTED':
        _require(m.group(3) is not None, 'REPLY_S1_STEP_MISSING')
        return m.group(3), m.group(4), True
    _require(m.group(2) is not None and m.group(3) is None, 'REPLY_S1_STEP_MISSING')
    return m.group(2), m.group(1), False


def check_s1(found, task, spec, steps, capture_path, prompt_sha):
    _require(len(found['S1']) == 1, 'REPLY_S1_MISSING' if not found['S1'] else 'REPLY_S1_REPEATED')
    step, code, already = s1_line(found)
    _require(len(found['STATE']) == 1, 'REPLY_STATE_MISSING' if not found['STATE'] else 'REPLY_STATE_REPEATED')
    done, halted, _ = state(found)
    _require(done == steps[:len(done)], 'REPLY_STATE_MISMATCH')
    promo = {} if spec['kind'] == 'production' else {'CI_RUN_CANDIDATE': (0, 1), 'MAIN_PROMOTED': (0, 1)}
    base_ranges = dict({'S1': (1, 1), 'S1_DETAIL': (0, 1), 'TIMING': (1, 1), 'STATE': (1, 1),
                        'STEP_PASS': (0, len(steps))}, **promo)
    if halted == step + ':' + code:                                       # halt persisted inside the step
        _require(step in steps and done == steps[:steps.index(step)], 'REPLY_STATE_MISMATCH')
        ranges = dict(base_ranges, BOUNDED_EXIT=(0, len(STAGES)), BOUNDED_TIMEOUT=(0, 1))
        ranges.update({n: (1, 1) for n in METADATA} if not found['S1_EVIDENCE_STATUS'] else {'S1_EVIDENCE_STATUS': (1, 1)})
        ranges.update({n: (1, 1) for n in CAPTURE} if not found['S1_FULL_CAPTURE_STATUS'] else
                      {'S1_FULL_CAPTURE_STATUS': (1, 1)})
        if already:                                                      # the halted task printed nothing else
            ranges = dict(base_ranges)
        cardinality(found, ranges)
        check_bounded_lines(found, steps, step)
        persisted = True
    else:                                                                # stopped before the step body ran
        _require(halted == 'None' and not already, 'REPLY_STATE_MISMATCH')
        before = (code in PRECONTROL and step == 'preflight' and not done) or \
                 (code == 'CONTROL_MISSING' and step != 'preflight' and not done) or \
                 code in BEFORE_STEP or code.startswith('SPEC_')
        _require(before and (step in steps or code == 'UNKNOWN_STEP'), 'REPLY_STATE_MISMATCH')
        cardinality(found, base_ranges)
        persisted = False
    if found['CI_RUN_CANDIDATE']:
        check_ci(found, 'candidate', spec['candidate_branch'], spec['candidate_oid'])
    for p in found['MAIN_PROMOTED']:
        _require(p.group(1) == spec['candidate_oid'], 'REPLY_MAIN_MISMATCH')
    check_timing(found)
    check_step_pass(found, done)
    if not persisted or already:
        _require(capture_path is None, 'CAPTURE_NOT_EXPECTED')
        return 'S1 ' + step + ':' + code, 'N/A' if not persisted else 'NOT_VERIFIED', \
            'HALT_BEFORE_STEP' if not persisted else 'EVIDENCE_NOT_IN_REPLY'
    status, reason = s1_evidence(found, task, spec, step, code, capture_path, prompt_sha)
    return 'S1 ' + step + ':' + code, status, reason


def metadata(found, task, step, code):
    raw = one(found, 'S1_EVIDENCE_JSON').group(1)
    fm, sm = one(found, 'S1_EVIDENCE_FILE'), one(found, 'S1_SHA256SUMS_FILE')
    _require(fm.group(1) == '.git/' + task + '-s1-evidence.json' and sm.group(1) == '.git/' + task + '-s1-SHA256SUMS.txt',
             'REPLY_S1_EVIDENCE_FILE_MISMATCH')
    _require(hashlib.sha256((raw + '\n').encode('utf-8')).hexdigest() == fm.group(2), 'REPLY_S1_EVIDENCE_SHA_MISMATCH')
    meta = _json(raw, 'REPLY_S1_EVIDENCE_JSON_INVALID')
    _require(meta.get('kind') == 'S1_METADATA_ONLY' and meta.get('task_id') == task and meta.get('step') == step
             and meta.get('s1_code') == code and isinstance(meta.get('files'), list) and meta['files'],
             'REPLY_S1_EVIDENCE_BINDING_MISMATCH')
    entries = {}
    for e in meta['files']:
        _require(isinstance(e, dict) and set(e) == {'file', 'bytes', 'sha256'} and isinstance(e['file'], str)
                 and type(e['bytes']) is int and e['bytes'] >= 0 and isinstance(e['sha256'], str)
                 and SHA256.match(e['sha256']) is not None and e['file'] not in entries, 'REPLY_S1_EVIDENCE_JSON_INVALID')
        entries[e['file']] = e
    sums = ''.join(e['sha256'] + '  ' + e['file'] + '\n' for e in meta['files']).encode('ascii')
    _require(hashlib.sha256(sums).hexdigest() == sm.group(2), 'REPLY_S1_SHA256SUMS_MISMATCH')
    return raw, meta, entries, sums


def s1_evidence(found, task, spec, step, code, capture_path, prompt_sha):
    if step not in STAGES:
        _require(capture_path is None, 'CAPTURE_NOT_EXPECTED')
        return 'N/A', 'NOT_A_BOUNDED_STEP'
    stage, pre, post = STAGES[step]
    record = task + '-bounded-' + stage.lower() + '.txt'
    if code in post or any(m.group(1) == stage for m in found['BOUNDED_EXIT'] + found['BOUNDED_TIMEOUT']):
        started = 'STARTED'
    elif code in pre:
        started = 'NOT_STARTED'
    else:
        started = 'UNKNOWN'
    if not found['S1_EVIDENCE_JSON']:
        _require(capture_path is None, 'CAPTURE_NOT_EXPECTED')
        return 'NOT_VERIFIED', 'S1_METADATA_ABSENT'
    raw, meta, entries, sums = metadata(found, task, step, code)
    entry = entries.get(record)
    if started == 'NOT_STARTED':
        _require(capture_path is None, 'CAPTURE_NOT_EXPECTED')
        return ('N/A', 'BOUNDED_NOT_STARTED') if entry is None else ('NOT_VERIFIED', 'BOUNDED_START_CONTRADICTED')
    if entry is None or entry['bytes'] == 0:
        _require(capture_path is None, 'CAPTURE_NOT_EXPECTED')
        if started == 'STARTED':
            return 'INCOMPLETE', 'BOUNDED_RECORD_MISSING' if entry is None else 'BOUNDED_RECORD_EMPTY'
        return 'NOT_VERIFIED', 'BOUNDED_START_UNKNOWN'
    if capture_path is None:
        return 'NOT_VERIFIED', 'TEXT_ATTESTED_CAPTURE_NOT_GIVEN' if started == 'STARTED' else 'BOUNDED_START_UNKNOWN'
    verify_capture(found, task, spec, step, code, capture_path, prompt_sha, raw, meta, sums)
    return 'PASS', 'CAPTURE_VERIFIED'


def verify_capture(found, task, spec, step, code, capture_path, prompt_sha, raw_meta, meta, sums):
    _require(found['S1_FULL_CAPTURE_JSON'], 'CAPTURE_NOT_REPORTED')
    _require(prompt_sha is not None and SHA256.match(prompt_sha) is not None, 'CAPTURE_PROMPT_BINDING_MISSING')
    try:
        data = Path(capture_path).read_bytes()
    except OSError:
        raise CheckError('CAPTURE_UNREADABLE')
    fm, cm = one(found, 'S1_FULL_CAPTURE_FILE'), one(found, 'S1_FULL_CAPTURE_CARD')
    archive = task + '-s1-full-capture.zip'
    _require(fm.group(1) == '.git/' + archive, 'REPLY_S1_CAPTURE_FILE_MISMATCH')
    zsha = hashlib.sha256(data).hexdigest()
    _require(zsha == fm.group(2), 'CAPTURE_SHA_MISMATCH')
    raw = one(found, 'S1_FULL_CAPTURE_JSON').group(1)
    _require(cm.group(1) == '.git/' + task + '-s1-full-capture.json'
             and hashlib.sha256((raw + '\n').encode('utf-8')).hexdigest() == cm.group(2), 'REPLY_S1_CAPTURE_CARD_MISMATCH')
    card = _json(raw, 'REPLY_S1_CAPTURE_JSON_INVALID')
    _require(card.get('kind') == 'S1_FULL_CAPTURE' and card.get('complete_capture') is True and card.get('task_id') == task
             and card.get('step') == step and card.get('s1_code') == code and card.get('base_oid') == spec['base_oid']
             and card.get('archive_file') == archive and card.get('archive_sha256') == zsha, 'CAPTURE_CARD_BINDING_MISMATCH')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            _require(len(names) == len(set(names)) and 'SHA256SUMS.txt' in names, 'CAPTURE_MANIFEST_MISSING')
            members = {n: z.read(n) for n in names}
    except (zipfile.BadZipFile, ValueError, KeyError, OSError, EOFError):
        raise CheckError('CAPTURE_UNREADABLE')
    manifest = members.pop('SHA256SUMS.txt')
    expected = ''.join(hashlib.sha256(members[n]).hexdigest() + '  ' + n + '\n' for n in sorted(members)).encode('ascii')
    _require(manifest == expected and hashlib.sha256(manifest).hexdigest() == card.get('manifest_sha256')
             and card.get('archive_member_count') == len(members) + 1, 'CAPTURE_MANIFEST_MISMATCH')
    prompt = members.get(task + '-prompt.txt')
    _require(prompt is not None and hashlib.sha256(prompt).hexdigest() == prompt_sha, 'CAPTURE_PROMPT_MISMATCH')
    try:
        control = _json(members[task + '-control.json'].decode('utf-8'), 'CAPTURE_CONTROL_MISMATCH')
    except (KeyError, UnicodeDecodeError):
        raise CheckError('CAPTURE_CONTROL_MISMATCH')
    _require(control.get('task_id') == task and control.get('prompt_sha256') == prompt_sha
             and control.get('halted') == step + ':' + code, 'CAPTURE_CONTROL_MISMATCH')
    _require(members.get(task + '-s1-evidence.json') == (raw_meta + '\n').encode('utf-8')
             and members.get(task + '-s1-SHA256SUMS.txt') == sums, 'CAPTURE_METADATA_MISMATCH')
    for e in meta['files']:
        body = members.get(e['file'])
        _require(body is not None and len(body) == e['bytes'] and hashlib.sha256(body).hexdigest() == e['sha256'],
                 'CAPTURE_RECORD_MISMATCH')


def check_reply(prompt_path, reply_text, capture_path=None):
    task, data = prompt_builder.prompt_task(prompt_path)
    try:
        spec = batch_runner.load_spec(batch_runner.prompt_lines(data), task)
    except batch_runner.Halt:
        raise CheckError('PROMPT_SPEC_INVALID')
    return check_spec(task, spec, reply_text, capture_path, hashlib.sha256(data).hexdigest())


def check_spec(task, spec, reply_text, capture_path=None, prompt_sha=None):
    _require(spec['kind'] in ('production', 'promotion'), 'KIND_NOT_SUPPORTED')
    steps = batch_runner.derive_steps(spec)
    found = parse_lines(reply_text)
    if found['S1']:
        outcome, status, reason = check_s1(found, task, spec, steps, capture_path, prompt_sha)
    else:
        _require(capture_path is None, 'CAPTURE_NOT_EXPECTED')
        outcome, status, reason = check_success(found, task, spec, steps), 'N/A', 'NO_S1'
    _require(status != 'INCOMPLETE', 'EVIDENCE_INCOMPLETE_' + reason)
    return task, spec['kind'], outcome, status, reason


def main(argv=None):
    parser = argparse.ArgumentParser(description='Macro-side Executor reply check (B-119 G1 Q1).')
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--reply', required=True)
    parser.add_argument('--capture')
    args = parser.parse_args(argv)
    try:
        try:
            reply = Path(args.reply).read_bytes().decode('utf-8')
        except (OSError, UnicodeDecodeError):
            raise CheckError('REPLY_UNREADABLE')
        task, kind, outcome, status, reason = check_reply(args.prompt, reply, args.capture)
    except (CheckError, prompt_builder.BuildError) as e:
        print('REPLY_CHECK FAIL ' + str(e))
        return 1
    print('REPLY_CHECK TASK=' + task + ' KIND=' + kind + ' OUTCOME=' + outcome.replace(' ', '='))
    print('REPLY_CHECK FIELDS=PASS')
    print('REPLY_CHECK EVIDENCE=' + status + ' REASON=' + reason)
    result = 'PASS' if status in ('PASS', 'N/A') else 'NOT_VERIFIED'
    print('REPLY_CHECK RESULT=' + result)
    return 0 if result == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
