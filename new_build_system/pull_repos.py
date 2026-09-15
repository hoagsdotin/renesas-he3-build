#!/usr/bin/env python3
"""Pull the eterna / lotier repos, compile their firmware, and convert it.

Three stages per project, in order:

    1. git pull   the project's own branch (Eterna_automation / Lotier_automation)
    2. compile    from source with the project's toolchain (CC-RL / arm-gcc)
    3. convert    the .mot/.srec into the deliverable (.h / .bin)

Repo paths, branches, toolchains and output locations all come from
build_firmware.py's PROJECTS dict, so they are configured in one place.

Usage:
    python3 pull_repos.py                  # all three stages, both projects
    python3 pull_repos.py eterna           # just eterna
    python3 pull_repos.py lotier eterna    # both, in that order
    python3 pull_repos.py --no-pull        # compile + convert only
    python3 pull_repos.py --no-compile     # convert the checked-in image
    python3 pull_repos.py --no-build       # pull only
    python3 pull_repos.py --build mp       # eterna reads VERSION_*_MP
    python3 pull_repos.py --keep-going     # carry on even if the pull failed
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import build_firmware as bf
except ImportError:
    sys.exit(f"Error: build_firmware.py must sit next to this script ({_HERE})")


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("names", nargs="*", metavar="PROJECT",
                   help=f"any of: {', '.join(bf.PROJECTS)} (default: all)")
    p.add_argument("--no-pull", action="store_true", help="skip git pull")
    p.add_argument("--no-compile", action="store_true",
                   help="skip compiling; use the image checked into the repo")
    p.add_argument("--no-build", action="store_true",
                   help="skip compiling and converting (pull only)")
    p.add_argument("--build", default=None, choices=["dev", "test", "mp"],
                   help="eterna version block to read "
                        "(default: follow CURRENT_BUILD_TYPE in version.h)")
    p.add_argument("--merge", action="store_true",
                   help="allow a real merge instead of requiring a fast-forward")
    p.add_argument("--keep-going", action="store_true",
                   help="attempt the build even if the pull failed")
    p.add_argument("--list", action="store_true", help="show resolved paths")
    args = p.parse_args()

    names = args.names or list(bf.PROJECTS)
    unknown = [n for n in names if n not in bf.PROJECTS]
    if unknown:
        p.error(f"unknown project(s): {', '.join(unknown)}. "
                f"Known: {', '.join(bf.PROJECTS)}")

    if args.list:
        return bf.main_list(names)

    results = []
    for name in names:
        cfg = bf.PROJECTS[name]
        print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")

        pulled = True
        if not args.no_pull:
            try:
                bf.git_pull(name, cfg, ff_only=not args.merge)
            except Exception as e:
                print(f"  PULL FAILED: {e}")
                pulled = False

        if args.no_build:
            results.append((name, pulled))
            continue

        if not pulled and not args.keep_going:
            print("  build skipped (pull failed; use --keep-going to build anyway)")
            results.append((name, False))
            continue

        built = bf.build(name, cfg, args.build, do_pull=False, header=False,
                         do_compile=not args.no_compile)
        results.append((name, pulled and built))

    failed = [n for n, ok in results if not ok]
    print(f"\n{'=' * 60}")
    print(f"{len(results) - len(failed)}/{len(results)} succeeded")
    for n in failed:
        print(f"  failed: {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
