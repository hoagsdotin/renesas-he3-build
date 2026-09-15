#!/usr/bin/env python3
"""Check that this machine can run the build, and show every resolved path.

    python3 doctor.py

Exit status is non-zero if anything required is missing, so it can gate a
provisioning script.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config
import build_firmware as bf

OK, WARN, BAD = "ok", "warn", "MISSING"

# tool -> (required for, is it fatal)
TOOLS = [
    ("git", "everything", True),
    ("make", "both firmware builds", True),
    ("python3", "conversion scripts", True),
    ("rsync", "syncing projects into the work dir (falls back to cp)", False),
    ("ccrl", "RL78 firmware (CC-RL)", False),
    ("rlink", "RL78 link step", False),
    ("arm-none-eabi-gcc", "RA firmware and the HE3 SDK", False),
    ("jq", "HE3 versioning", False),
    ("zip", "HE3 build archive", False),
    ("unzip", "extracting device files from an installer", False),
    ("aws", "only for --ci (S3 upload)", False),
]


def line(status, label, value=""):
    mark = {"ok": "  ok  ", "warn": " warn ", "MISSING": " MISS "}[status]
    print(f"[{mark}] {label:22} {value}")


def main():
    problems, warnings = 0, 0

    print("=" * 72)
    print("paths")
    print("=" * 72)
    for label, value, ok in config.summary():
        if ok:
            line(OK, label, value)
        else:
            # a missing workroot/output dir is created on demand; only flag
            # things that must already exist
            if label in ("workspace", "he3 scripts"):
                line(BAD, label, value)
                problems += 1
            else:
                line(WARN, label, value)
                warnings += 1

    print()
    print("=" * 72)
    print("tools")
    print("=" * 72)
    # Search the same PATH the build will actually use, otherwise a perfectly
    # good CC-RL install reports as missing just because it is not on the
    # interactive PATH.
    search_path = os.pathsep.join(
        config.extra_tool_paths() + [os.environ.get("PATH", "")])

    for tool, why, fatal in TOOLS:
        path = shutil.which(tool, path=search_path)
        if path:
            line(OK, tool, path)
        elif fatal:
            line(BAD, tool, f"required for {why}")
            problems += 1
        else:
            line(WARN, tool, f"needed for {why}")
            warnings += 1

    print()
    print("=" * 72)
    print("projects")
    print("=" * 72)
    for name, cfg in bf.PROJECTS.items():
        repo = cfg["repo"]
        exists = os.path.isdir(os.path.join(repo, ".git"))
        line(OK if exists else BAD, name, repo)
        if not exists:
            problems += 1
            # Keep going far enough to report the device file too, so a fresh
            # machine sees every prerequisite in one pass instead of
            # discovering them one run at a time.
            comp = cfg.get("compile")
            if comp and comp["toolchain"] == "ccrl":
                dev = comp.get("device_file")
                if not (dev and os.path.isfile(dev)):
                    line(BAD, "  device file",
                         f"{comp.get('device_file_name', '?')} not found "
                         "- see README step 2")
                    problems += 1
            continue

        try:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo,
                capture_output=True, text=True, timeout=30).stdout.strip()
            want = cfg["branch"]
            line(OK if branch == want else WARN, "  branch",
                 f"{branch}" + ("" if branch == want else f"  (expected {want})"))
            if branch != want:
                warnings += 1
        except Exception as e:
            line(WARN, "  branch", str(e))
            warnings += 1

        comp = cfg.get("compile")
        if comp:
            line(OK, "  toolchain", comp["toolchain"])
            dev = comp.get("device_file")
            if comp["toolchain"] == "ccrl":
                if dev and os.path.isfile(dev):
                    line(OK, "  device file", dev)
                else:
                    line(BAD, "  device file",
                         f"{comp.get('device_file_name', '?')} not found - "
                         "RL78 link will fail")
                    problems += 1
        out = bf.resolve_output(cfg)
        line(OK if os.path.isfile(out) else WARN, "  last output", out)

    print()
    print("=" * 72)
    if problems:
        print(f"{problems} problem(s), {warnings} warning(s)")
        print("Fix the MISS entries above before building.")
    else:
        print(f"ready. {warnings} warning(s) - optional tools or first run.")
    print("=" * 72)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
