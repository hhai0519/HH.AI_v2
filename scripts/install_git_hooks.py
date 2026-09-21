#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/install_git_hooks.py

Local Repository Git Hook Installer and Checker (ADR-0016 / SECRET-8 / TG-MVP-06-F1).

CLI:
  python scripts/install_git_hooks.py --install
  python scripts/install_git_hooks.py --check

Invariants:
- Only manages local repository Git config: `git config --local core.hooksPath .githooks`.
- Never modifies global or system Git config.
- Never modifies user profile or OS policy.
- Fail-closed: exits non-zero if `.githooks/pre-commit` is missing, not a regular file,
  lacks execute permission on POSIX, or hooksPath does not match.
"""

import os
import sys
import subprocess
import argparse

CANONICAL_HOOKS_PATH = ".githooks"
REQUIRED_HOOKS = ["pre-commit", "pre-push"]


def get_repo_root():
    try:
        out = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True)
        return out.strip()
    except Exception as e:
        sys.stderr.write(f"Error: Failed to determine repository root: {e}\n")
        return None


def install_hooks():
    repo_root = get_repo_root()
    if not repo_root:
        return 1

    for hook_name in REQUIRED_HOOKS:
        hook_file = os.path.join(repo_root, CANONICAL_HOOKS_PATH, hook_name)

        # 1 & 2: Check canonical hook file exists and is regular file
        if not os.path.exists(hook_file):
            sys.stderr.write(f"HOOK_INSTALL FAIL: Required hook file does not exist: '{hook_file}'\n")
            return 1

        if not os.path.isfile(hook_file) or os.path.islink(hook_file):
            sys.stderr.write(f"HOOK_INSTALL FAIL: Hook path is not a regular file: '{hook_file}'\n")
            return 1

        # 3 & 4: On POSIX, attempt chmod and verify execute permission (no swallowed chmod failure)
        if os.name != 'nt':
            try:
                os.chmod(hook_file, 0o755)
            except Exception as err:
                sys.stderr.write(f"HOOK_INSTALL FAIL: Failed to set executable mode on hook: {err}\n")
                return 1

            if not os.access(hook_file, os.X_OK):
                sys.stderr.write(f"HOOK_INSTALL FAIL: Hook file is not executable after chmod on POSIX: '{hook_file}'\n")
                return 1

    # 5: Set local core.hooksPath only after all hooks' usability is established
    try:
        subprocess.check_call(
            ['git', 'config', '--local', 'core.hooksPath', CANONICAL_HOOKS_PATH],
            cwd=repo_root
        )
    except subprocess.CalledProcessError as err:
        sys.stderr.write(f"HOOK_INSTALL FAIL: Failed to set local core.hooksPath: {err}\n")
        return 1

    sys.stdout.write(f"HOOK_INSTALL PASS: core.hooksPath set to '{CANONICAL_HOOKS_PATH}'\n")
    return 0


def check_hooks():
    repo_root = get_repo_root()
    if not repo_root:
        return 1

    # A: Verify core.hooksPath
    try:
        current_val = subprocess.check_output(
            ['git', 'config', '--local', '--get', 'core.hooksPath'],
            cwd=repo_root,
            text=True
        ).strip()
    except subprocess.CalledProcessError:
        sys.stderr.write("HOOK_CHECK FAIL: core.hooksPath is not set in local repository config\n")
        return 1

    norm_val = current_val.replace('\\', '/')
    if norm_val != CANONICAL_HOOKS_PATH:
        sys.stderr.write(
            f"HOOK_CHECK FAIL: core.hooksPath is '{current_val}', expected '{CANONICAL_HOOKS_PATH}'\n"
        )
        return 1

    # B & C: Verify hook files exist and are regular files
    for hook_name in REQUIRED_HOOKS:
        hook_file = os.path.join(repo_root, CANONICAL_HOOKS_PATH, hook_name)
        if not os.path.exists(hook_file):
            sys.stderr.write(f"HOOK_CHECK FAIL: Required hook file does not exist: '{hook_file}'\n")
            return 1

        if not os.path.isfile(hook_file) or os.path.islink(hook_file):
            sys.stderr.write(f"HOOK_CHECK FAIL: Hook path is not a regular file: '{hook_file}'\n")
            return 1

        # D: On POSIX, verify executable permission
        if os.name != 'nt':
            if not os.access(hook_file, os.X_OK):
                sys.stderr.write(f"HOOK_CHECK FAIL: Hook file is not executable (+x): '{hook_file}'\n")
                return 1

    sys.stdout.write(f"HOOK_CHECK PASS: core.hooksPath is '{CANONICAL_HOOKS_PATH}' (all {len(REQUIRED_HOOKS)} hooks verified)\n")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Git Hooks Local Manager")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--install', action='store_true', help="Install local core.hooksPath")
    group.add_argument('--check', action='store_true', help="Verify local core.hooksPath configuration")

    args = parser.parse_args()

    if args.install:
        return install_hooks()
    elif args.check:
        return check_hooks()
    return 1


if __name__ == '__main__':
    sys.exit(main())
