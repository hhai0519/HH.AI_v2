#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/install_git_hooks.py

Local Repository Git Hook Installer and Checker (ADR-0016 / SECRET-8).

CLI:
  python scripts/install_git_hooks.py --install
  python scripts/install_git_hooks.py --check

Invariants:
- Only manages local repository Git config: `git config --local core.hooksPath .githooks`.
- Never modifies global or system Git config.
- Never modifies user profile or OS policy.
- Fail-closed: exits non-zero if `.githooks/pre-commit` is missing or hooksPath does not match.
"""

import os
import sys
import subprocess
import argparse

CANONICAL_HOOKS_PATH = ".githooks"


def get_repo_root():
    out = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True)
    return out.strip()


def install_hooks():
    repo_root = get_repo_root()
    hook_file = os.path.join(repo_root, CANONICAL_HOOKS_PATH, "pre-commit")

    if not os.path.exists(hook_file):
        sys.stderr.write(f"Error: Required hook file does not exist: '{hook_file}'\n")
        return 1

    try:
        subprocess.check_call(
            ['git', 'config', '--local', 'core.hooksPath', CANONICAL_HOOKS_PATH],
            cwd=repo_root
        )
        if os.name != 'nt':
            try:
                os.chmod(hook_file, 0o755)
            except Exception:
                pass
        sys.stdout.write(f"HOOK_INSTALL PASS: core.hooksPath set to '{CANONICAL_HOOKS_PATH}'\n")
        return 0
    except subprocess.CalledProcessError as err:
        sys.stderr.write(f"Error: Failed to set local core.hooksPath: {err}\n")
        return 1


def check_hooks():
    repo_root = get_repo_root()
    try:
        current_val = subprocess.check_output(
            ['git', 'config', '--local', '--get', 'core.hooksPath'],
            cwd=repo_root,
            text=True
        ).strip()
    except subprocess.CalledProcessError:
        sys.stderr.write("HOOK_CHECK FAIL: core.hooksPath is not set in local repository config\n")
        return 1

    # Normalize forward/backward slashes
    norm_val = current_val.replace('\\', '/')
    if norm_val != CANONICAL_HOOKS_PATH:
        sys.stderr.write(
            f"HOOK_CHECK FAIL: core.hooksPath is '{current_val}', expected '{CANONICAL_HOOKS_PATH}'\n"
        )
        return 1

    sys.stdout.write(f"HOOK_CHECK PASS: core.hooksPath is '{CANONICAL_HOOKS_PATH}'\n")
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
