#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/secret_presence.py

Safe Environment Variable Presence Checker (B-98 / SECRET-2 / TG-MVP-06-F1).

Invariants:
- Exactly one environment variable name per invocation.
- Exact-name lookup only via os.environ.get(name).
- Zero environment iteration, zero key/item/value enumeration.
- Strictly rejects wildcards (*, ?), prefix queries, or invalid identifier syntax.
- Emits ONLY 'PRESENT' or 'ABSENT'.
- ZERO caller-supplied argument echo, variable name echo, secret value, length,
  hash, digest, prefix/suffix, or partial mask output.
- Non-empty value => PRESENT; missing or empty => ABSENT.
- Fail-closed on invalid arguments or syntax errors (exit code 1) with fixed
  generic error messages (no user input interpolation).
"""

import sys
import re
import os

# Standard environment variable name pattern: uppercase/lowercase letters, digits, underscores.
# Non-empty, does not start with digit.
ENV_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
FORBIDDEN_CHARS = ('*', '?', '%', '$', ':', ';', '/', '\\', ' ')


def check_presence(env_names):
    if not env_names or len(env_names) != 1:
        sys.stderr.write("SECRET_PRESENCE ERROR invalid-arguments\n")
        return 1

    name = env_names[0]
    if not name or not isinstance(name, str):
        sys.stderr.write("SECRET_PRESENCE ERROR invalid-name\n")
        return 1

    trimmed = name.strip()
    if trimmed != name:
        sys.stderr.write("SECRET_PRESENCE ERROR invalid-whitespace\n")
        return 1

    # Reject wildcard, prefix, or invalid characters
    if any(ch in name for ch in FORBIDDEN_CHARS):
        sys.stderr.write("SECRET_PRESENCE ERROR forbidden-characters\n")
        return 1

    if not ENV_NAME_PATTERN.match(name):
        sys.stderr.write("SECRET_PRESENCE ERROR invalid-syntax\n")
        return 1

    # Exact lookup only: use os.environ.get without iterating os.environ
    # Value is never exposed or logged.
    val = None
    try:
        val = os.environ.get(name)
    except Exception:
        sys.stderr.write("SECRET_PRESENCE ERROR lookup-failed\n")
        return 1

    if val is not None and len(val) > 0:
        sys.stdout.write("PRESENT\n")
    else:
        sys.stdout.write("ABSENT\n")

    return 0


def main():
    return check_presence(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
