#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C9 R2: read-only inventory of off-HEAD local history before recovery.

Never switches, saves, deletes, fetches, or writes any Git ref or worktree file.
READY means only that no branch tip contains commits absent from the pinned
Base at this instant; it is not a recovery, deletion, or checkout permit.
"""
import argparse
import json
import re
import sys

from c9_base_guard import OID, classify, _git

COUNT = re.compile(r'^(0|[1-9][0-9]{0,9})$')
MAX_LOCAL_HEADS = 64


def inventory(repo, base):
    # Existing R1 remote/HEAD/worktree guard is necessary, but insufficient:
    # off-HEAD branches can still retain local S1 commits when HEAD==Base.
    current = classify(repo, base)
    if current['status'] != 'READY':
        return {'status': 'HOLD', 'reason': 'BASE_GUARD_' + current['reason']}

    raw = _git(repo, 'for-each-ref', '--format=%(objectname)', 'refs/heads')
    tips = raw.splitlines()
    if not tips or len(tips) > MAX_LOCAL_HEADS:
        return {'status': 'HOLD', 'reason': 'LOCAL_HEAD_SET_UNBOUNDED'}
    if any(not OID.fullmatch(tip) for tip in tips):
        return {'status': 'HOLD', 'reason': 'LOCAL_HEAD_OID_INVALID'}

    # A branch ahead of or divergent from Base must be preserved. This is
    # conservative: even a previously pushed, unmerged branch will HOLD.
    for tip in tips:
        if tip == base:
            continue
        n = _git(repo, 'rev-list', '--count', base + '..' + tip)
        if not COUNT.fullmatch(n):
            return {'status': 'HOLD', 'reason': 'LOCAL_HISTORY_COUNT_INVALID'}
        if int(n) > 0:
            return {'status': 'HOLD', 'reason': 'OFF_HEAD_HISTORY_PRESERVE'}

    # One final R1 recheck narrows normal drift; not a transaction or lease.
    final = classify(repo, base)
    if final['status'] != 'READY':
        return {'status': 'HOLD', 'reason': 'BASE_GUARD_DRIFT'}
    return {'status': 'READY', 'reason': 'NO_OFF_HEAD_UNMERGED_HISTORY',
            'local_head_count': len(tips), 'base': base,
            'authorization': 'NONE', 'snapshot_only': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only C9 R2 off-HEAD preservation check')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--base-oid', required=True)
    args = parser.parse_args(argv)
    try:
        result = inventory(args.repo, args.base_oid)
    except RuntimeError as exc:
        result = {'status': 'HOLD', 'reason': str(exc)}
    # Never expose branch names, dirty filenames or source contents.
    print('C9_HISTORY_GUARD_JSON=' + json.dumps(result, ensure_ascii=True, sort_keys=True,
                                                separators=(',', ':')))
    return 0 if result['status'] == 'READY' else 1


if __name__ == '__main__':
    sys.exit(main())
