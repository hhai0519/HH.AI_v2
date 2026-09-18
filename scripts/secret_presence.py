#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/secret_presence.py

Safe Environment Variable Presence Checker (B-98 / SECRET-2).

Invariants:
- Exact-name lookup only via os.environ.get(name).
- Zero environment iteration, zero key/item enumeration.
- Strictly rejects wildcards (*, ?), prefix queries, or invalid identifier syntax.
- Emits ONLY '<NAME>=PRESENT' or '<NAME>=ABSENT'.
- ZERO secret value, length, hash, digest, prefix/suffix, or partial mask output.
- Non-empty value => PRESENT; missing or empty => ABSENT.
- Fail-closed on invalid arguments or syntax errors (exit code 1).
"""

import sys
import re

# Standard environment variable name pattern: uppercase/lowercase letters, digits, underscores.
# Non-empty, does not start with digit.
ENV_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def check_presence(env_names):
    if not env_names:
        sys.stderr.write("Error: At least one environment variable name is required.\n")
        sys.stderr.write("Usage: python scripts/secret_presence.py <ENV_NAME> [<ENV_NAME>...]\n")
        return 1

    has_error = False
    results = []

    for name in env_names:
        if not name or not isinstance(name, str):
            sys.stderr.write(f"Error: Invalid argument: '{name}'\n")
            has_error = True
            continue

        trimmed = name.strip()
        if trimmed != name:
            sys.stderr.write(f"Error: Environment variable name contains leading/trailing whitespace: '{name}'\n")
            has_error = True
            continue

        # Reject wildcard or prefix query characters
        if any(ch in name for ch in ('*', '?', '%', '$', ':', ';', '/', '\\', ' ')):
            sys.stderr.write(f"Error: Wildcard, prefix, or invalid characters forbidden in exact-lookup: '{name}'\n")
            has_error = True
            continue

        if not ENV_NAME_PATTERN.match(name):
            sys.stderr.write(f"Error: Invalid environment variable name syntax: '{name}'\n")
            has_error = True
            continue

        # Exact lookup only: use os.environ.get without iterating os.environ
        # Value is never exposed or logged.
        val = None
        try:
            import os
            val = os.environ.get(name)
        except Exception as err:
            sys.stderr.write(f"Error checking environment variable '{name}': {err}\n")
            has_error = True
            continue

        if val is not None and len(val) > 0:
            results.append(f"{name}=PRESENT")
        else:
            results.append(f"{name}=ABSENT")

    if has_error:
        return 1

    for line in results:
        sys.stdout.write(line + "\n")

    return 0


def main():
    return check_presence(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
