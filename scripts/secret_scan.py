#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/secret_scan.py

Commit-Time & Tracked Secret / Credential Scanner (ADR-0016 / TG-MVP-06).

Modes:
  --staged   Scans prospective Git index commit (reads index blobs, not working tree).
  --tracked  Scans all tracked working-tree files (used for CHECK 21 and CI).

Invariants:
- Pure Python standard library only.
- Fail-closed: exits with code 1 if any secret or forbidden filename is detected.
- Safe output contract: NEVER prints matched secret values, partial tokens, hashes,
  lengths, or context lines.
  Only outputs:
    SECRET_SCAN BLOCK detector=<ID> path=<PATH> line=<N>
    or:
    SECRET_SCAN PASS mode=<MODE>
"""

import os
import sys
import re
import subprocess
import argparse

# ---------------------------------------------------------------------------
# 1. Forbidden Filename Guard (§25)
# ---------------------------------------------------------------------------

EXEMPT_TEMPLATE_FILENAMES = {
    '.env.example',
    '.env.sample',
    '.env.template',
}

FORBIDDEN_EXACT_OR_PATTERN_FILENAMES = [
    re.compile(r'(?:^|[/\\])[^/\\]*cookies[^/\\]*$', re.IGNORECASE),
    re.compile(r'(?:^|[/\\])mcp_config[^/\\]*\.json$', re.IGNORECASE),
    re.compile(r'(?:^|[/\\])\.env$', re.IGNORECASE),
    re.compile(r'(?:^|[/\\])\.env\.(?!example$|sample$|template$)[^/\\]+$', re.IGNORECASE),
    re.compile(r'(?:^|[/\\])credentials[^/\\]*\.json$', re.IGNORECASE),
    re.compile(r'(?:^|[/\\])id_rsa(?:|\.[^/\\]+)$', re.IGNORECASE),
    re.compile(r'(?:^|[/\\])id_ed25519(?:|\.[^/\\]+)$', re.IGNORECASE),
    re.compile(r'(?:^|[/\\])[^/\\]+\.(?:p12|pfx|key)$', re.IGNORECASE),
]


def check_forbidden_filename(path):
    """
    Returns detector ID if path matches a forbidden filename, or None.
    """
    basename = os.path.basename(path).lower()
    if basename in EXEMPT_TEMPLATE_FILENAMES:
        return None

    norm_path = path.replace('\\', '/')
    for pattern in FORBIDDEN_EXACT_OR_PATTERN_FILENAMES:
        if pattern.search(norm_path):
            return "FILENAME_FORBIDDEN"
    return None


# ---------------------------------------------------------------------------
# 2. Content Detectors (§24)
# ---------------------------------------------------------------------------

# Placeholder keywords that denote obvious test fixtures, documentation examples, or templates
PLACEHOLDER_REGEX = re.compile(
    r'(?:SYNTHETIC|FAKE|EXAMPLE|PLACEHOLDER|REDACTED|DUMMY|TEST|CHANGEME|<[^>]+>|\$\{[^}]+\}|__[A-Z0-9_]+__)',
    re.IGNORECASE
)

# Individual signature patterns with detector IDs
SIGNATURE_PATTERNS = [
    # A. GitHub Personal Access Tokens / App Tokens / Fine-grained PATs
    (
        "GITHUB_CREDENTIAL",
        re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{82,}\b')
    ),
    # B. Notion integration tokens
    (
        "NOTION_CREDENTIAL",
        re.compile(r'\bntn_[A-Za-z0-9]{30,}\b|\bsecret_[A-Za-z0-9]{40,}\b')
    ),
    # C. Telegram Bot Token: numeric bot id + colon + 35 character secret
    (
        "TELEGRAM_BOT_TOKEN",
        re.compile(r'\b\d{8,10}:[A-Za-z0-9_-]{35}\b')
    ),
    # D. Google Session Cookies
    (
        "GOOGLE_SESSION_COOKIE",
        re.compile(r'\b(?:__Secure-)?OSID=[A-Za-z0-9_-]{30,}\b')
    ),
    # E. Private Key Markers
    (
        "PRIVATE_KEY_MATERIAL",
        re.compile(r'-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----')
    ),
    # F. Generic Key/Secret assignments with long non-placeholder values
    (
        "GENERIC_SECRET_ASSIGNMENT",
        re.compile(
            r'''(?i)\b(?:api[_-]?key|apikey|access[_-]?token|client[_-]?secret|password|token|secret)\b\s*[:=]\s*['"]([A-Za-z0-9_\-\.]{32,})['"]'''
        )
    ),
    # G. LINE Channel Access Token / Channel Secret field contexts
    (
        "LINE_CREDENTIAL",
        re.compile(
            r'''(?i)\b(?:line_channel_access_token|channel_access_token|line_channel_secret|channel_secret)\b\s*[:=]\s*['"]([A-Za-z0-9+/=_\-]{30,})['"]'''
        )
    ),
]


def scan_content_lines(content_bytes, file_path):
    """
    Scans file content lines for secret signatures.
    Yields (detector_id, line_number) tuples.
    """
    # Attempt to decode as utf-8, fallback to latin-1 for arbitrary byte streams
    try:
        text = content_bytes.decode('utf-8')
    except UnicodeDecodeError:
        text = content_bytes.decode('latin-1', errors='replace')

    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        # Scan each detector
        for detector_id, pattern in SIGNATURE_PATTERNS:
            for match in pattern.finditer(line):
                matched_str = match.group(0)

                # Check if the matched string or surrounding assignment value is an obvious placeholder
                if detector_id in ("GENERIC_SECRET_ASSIGNMENT", "LINE_CREDENTIAL"):
                    # Check the captured group if available
                    val = match.group(1) if match.lastindex and match.lastindex >= 1 else matched_str
                    if PLACEHOLDER_REGEX.search(val):
                        continue
                else:
                    if PLACEHOLDER_REGEX.search(matched_str):
                        continue

                # Also skip if the line itself contains an explicit documentation placeholder marker
                if PLACEHOLDER_REGEX.search(line):
                    # Check if the match itself looks like synthetic or placeholder
                    if any(ph in matched_str.upper() for ph in ("SYNTHETIC", "FAKE", "EXAMPLE", "PLACEHOLDER", "TEST")):
                        continue

                yield (detector_id, idx)


# ---------------------------------------------------------------------------
# 3. Mode Execution: Staged & Tracked
# ---------------------------------------------------------------------------

def get_repo_root():
    out = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True)
    return out.strip()


def run_staged_scan(repo_root=None):
    """
    Scans the staged prospective commit from the Git index.
    """
    if repo_root is None:
        repo_root = get_repo_root()

    # Get staged changes with status: A (added), C (copied), M (modified), R (renamed), D (deleted)
    diff_output = subprocess.check_output(
        ['git', 'diff', '--cached', '--name-status', '-z'],
        cwd=repo_root
    )

    if not diff_output:
        return []

    # Tokens separated by null byte
    raw_tokens = diff_output.split(b'\x00')
    tokens = [t.decode('utf-8', errors='replace') for t in raw_tokens if t]

    staged_items = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        if not status:
            i += 1
            continue

        status_code = status[0].upper()
        if status_code in ('R', 'C'):
            # Renamed or copied has old_path and new_path
            old_path = tokens[i + 1]
            new_path = tokens[i + 2]
            staged_items.append((status_code, new_path))
            i += 3
        else:
            path = tokens[i + 1]
            staged_items.append((status_code, path))
            i += 2

    findings = []

    for status_code, path in staged_items:
        # 1. Filename guard: applies to all prospective additions / renames / modifications
        if status_code != 'D':
            fn_detector = check_forbidden_filename(path)
            if fn_detector:
                findings.append((fn_detector, path, 1))

        # 2. Content scan: skip deleted files
        if status_code == 'D':
            continue

        # Read prospective blob from Git index: git show :<path>
        try:
            blob_bytes = subprocess.check_output(
                ['git', 'show', f':{path}'],
                cwd=repo_root,
                stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            # File might be a submodule or broken symlink in index
            continue

        for det_id, line_num in scan_content_lines(blob_bytes, path):
            findings.append((det_id, path, line_num))

    return findings


def run_tracked_scan(repo_root):
    """
    Scans all tracked working-tree regular files.
    """
    ls_output = subprocess.check_output(
        ['git', 'ls-files', '-z'],
        cwd=repo_root
    )

    raw_paths = ls_output.split(b'\x00')
    tracked_paths = [p.decode('utf-8', errors='replace') for p in raw_paths if p]

    findings = []

    for rel_path in tracked_paths:
        # 1. Filename guard
        fn_detector = check_forbidden_filename(rel_path)
        if fn_detector:
            findings.append((fn_detector, rel_path, 1))

        full_path = os.path.join(repo_root, rel_path)
        if not os.path.isfile(full_path):
            continue

        try:
            with open(full_path, 'rb') as f:
                content_bytes = f.read()
        except OSError:
            continue

        for det_id, line_num in scan_content_lines(content_bytes, rel_path):
            findings.append((det_id, rel_path, line_num))

    return findings


def main():
    parser = argparse.ArgumentParser(description="Deterministic Secret & Credential Scanner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--staged', action='store_true', help="Scan staged prospective commit from Git index")
    group.add_argument('--tracked', action='store_true', help="Scan all tracked files in the repository")

    args = parser.parse_args()
    repo_root = get_repo_root()

    if args.staged:
        mode = "STAGED"
        findings = run_staged_scan(repo_root)
    else:
        mode = "TRACKED"
        findings = run_tracked_scan(repo_root)

    if findings:
        for det_id, path, line_num in findings:
            # Safe output contract: strictly detector ID, path, and line number only
            sys.stdout.write(f"SECRET_SCAN BLOCK detector={det_id} path={path} line={line_num}\n")
        return 1
    else:
        sys.stdout.write(f"SECRET_SCAN PASS mode={mode}\n")
        return 0


if __name__ == '__main__':
    sys.exit(main())
