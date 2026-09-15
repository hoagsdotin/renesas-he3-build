#!/usr/bin/env python3
"""DEPRECATED -- use ./hoags-build instead.

This was an early copy of pull_repos.py. It carried its own hardcoded repo
paths, which then drifted from the real configuration, and its help text
still described "api"/"web" repos that never existed here.

It now forwards to the current pipeline so there is exactly one place that
knows where anything lives (config.py). Equivalent commands:

    build_renesas.py            ->  ./hoags-build firmware
    build_renesas.py eterna     ->  ./hoags-build firmware eterna
    build_renesas.py --list     ->  ./hoags-build list

Safe to delete once nothing references it.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

print(__doc__.split("\n")[0], file=sys.stderr)
print(f"forwarding to: {os.path.join(_HERE, 'pull_repos.py')}\n", file=sys.stderr)

import pull_repos

if __name__ == "__main__":
    sys.exit(pull_repos.main())
