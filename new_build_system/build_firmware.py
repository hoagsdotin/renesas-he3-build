#!/usr/bin/env python3
"""Compile and convert Renesas firmware images for the eterna and lotier projects.

Each project runs three stages:

    git pull  ->  compile from source  ->  convert to the deliverable

  eterna  CC-RL    -> DIY_Purifier.mot   --motTohex.py-->        renesas_firmware.h
  lotier  arm-gcc  -> RAseriesTEST1.srec --reneses_img_gen.py--> reneses.bin

Compiling happens in a work directory (build/compile/<project>/), never in the
git checkout: the RL78 projects track their .obj/.d files, so building in place
would dirty the tree and make the next --ff-only pull fail.

Usage:
    python3 build_firmware.py                 # compile + convert both
    python3 build_firmware.py eterna          # just one
    python3 build_firmware.py --pull          # pull, then compile + convert
    python3 build_firmware.py --no-compile    # convert the checked-in image
    python3 build_firmware.py --build mp      # eterna version block: DEV/TEST/MP
    python3 build_firmware.py --list          # show resolved paths and exit

Use pull_repos.py to always pull first; it is the usual entry point.
"""

import argparse
import glob
import re
import os
import shutil
import subprocess
import sys
import tempfile

# Path resolution lives in config.py so nothing here hardcodes an absolute
# location. Imported before PROJECTS, which is built from it.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import config

# --- configuration --------------------------------------------------------
# Repo-relative paths are written with backslashes exactly as they appear in
# the projects; they are split and rejoined so this works on Linux and Windows.

PROJECTS = {
    "lotier": {
        "repo": config.project_repo("lotier", "lotier_automation/External"),
        "branch": "Lotier_automation",
        "kind": "srec",
        # directory; the .srec inside it is discovered
        "source": r"Renesas\WaterPurifier\RAseriesTEST1_waterpurifier_latest\RAseriesTEST1\Debug",
        "output": "build/reneses.bin",
        # Compiled from source before conversion. See compile_firmware.py for
        # the Linux fixups these Windows-authored projects need.
        "compile": {
            "toolchain": "gcc-arm",          # arm-none-eabi-gcc, RA2E1 / R7FA2E1A92DFM
            "project": r"Renesas\WaterPurifier\RAseriesTEST1_waterpurifier_latest\RAseriesTEST1",
            "build_subdir": "Debug",
            "make_target": "all",
            "artifact": "RAseriesTEST1.srec",
        },
    },
    "eterna": {
        "repo": config.project_repo("eterna", "eterna_automation/External"),
        "branch": "Eterna_automation",
        "kind": "mot",
        # Fallback for --no-compile only. The .mot committed here is a stale
        # Windows build artifact; with compiling enabled (the default) the
        # freshly built image is used instead.
        "source": r"Renesas\DISPENSER_WAAS\DISPENSER_WAAS_Purifier\DIY_Purifier\HardwareDebug\DIY_Purifier.mot",
        # motTohex.py needs a Version.h to read VERSION_MAJOR_* / VERSION_MINOR_*
        "version_h": r"Renesas\DISPENSER_WAAS\DISPENSER_WAAS_Purifier\DIY_Purifier\src\version.h",
        # Pin the version written into the generated header. version.h's
        # VERSION_MINOR_TEST is 0, but the number the HE3 header has always
        # carried is 61 (VERSION_PATCH_* is what actually tracks releases).
        # Held at 61 deliberately: do not auto-increment.
        "version_override": {"major": 0, "minor": 61},
        "output": "build/renesas_firmware.h",
        "compile": {
            "toolchain": "ccrl",             # Renesas CC-RL, RL78/G16 / R5F121BCxFP
            "project": r"Renesas\DISPENSER_WAAS\DISPENSER_WAAS_Purifier\DIY_Purifier",
            "build_subdir": "HardwareDebug",
            "make_target": "DIY_Purifier.mot",
            "artifact": "DIY_Purifier.mot",
            # Required: rlink cannot resolve the RL78 RAM mirror region
            # without it. Located by config.find_device_file(), which searches
            # the workspace, a system install and any e2 studio device pack;
            # set HOAGS_DEVICE_FILE to point at it directly.
            "device_file_name": "DR5F121BC.DVF",
            "device_file": config.find_device_file("DR5F121BC.DVF"),
            # built after the .mot, for debugging; failure here is not fatal
            "extra_targets": ["DIY_Purifier.x"],
        },
    },
}

# Where motTohex.py and reneses_img_gen.py live. Defaults to this script's dir.
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

try:
    import compile_firmware
except ImportError:          # compiling is optional; --no-compile still works
    compile_firmware = None

TIMEOUT = 300
# Credentials come from the environment / secrets file via GIT_ASKPASS, so
# no token needs to live in any remote URL. GIT_TERMINAL_PROMPT=0 keeps git
# failing fast instead of blocking on a hidden prompt.
ENV = config.git_env()
# --------------------------------------------------------------------------


def candidates(repo, relative):
    """Every path we would accept for a repo-relative source, best first.

    The repo root may itself be the External/ directory, so a source written
    as External\\Renesas\\... can legitimately mean either
    <repo>/External/Renesas/... or <repo>/Renesas/... .
    """
    parts = [x for x in relative.replace("\\", "/").split("/") if x]
    out = [os.path.join(repo, *parts)]
    if parts and os.path.basename(os.path.normpath(repo)).lower() == parts[0].lower():
        out.append(os.path.join(repo, *parts[1:]))
    # also try the repo's parent, in case repo points one level too deep
    parent = os.path.dirname(os.path.normpath(os.path.abspath(repo)))
    out.append(os.path.join(parent, *parts))

    seen, unique = set(), []
    for c in out:
        key = os.path.normpath(os.path.abspath(c))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def winpath(repo, relative):
    """Join a backslash-separated repo-relative path onto repo, OS-correctly.

    The repo root may itself be the External/ directory, in which case a
    source path written as External\\Renesas\\... would double up. If the
    first component of the relative path repeats the repo's last component,
    and dropping it gives something that exists, use that instead.
    """
    cands = candidates(repo, relative)
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


def resolve_output(cfg):
    """Absolute path for a project's output file.

    Relative outputs resolve against the PARENT of the repo directory, not
    the repo itself, so generated artifacts land beside External/ instead of
    inside the tracked tree where they would dirty the working copy and
    block --ff-only pulls. An absolute output path is used as given.
    """
    out = cfg["output"]
    if os.path.isabs(out):
        return out
    parent = os.path.dirname(os.path.normpath(os.path.abspath(cfg["repo"])))
    return os.path.join(parent, *out.replace("\\", "/").split("/"))


def run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("env", ENV)
    kw.setdefault("timeout", TIMEOUT)
    return subprocess.run(cmd, **kw)


def is_git_repo(path):
    """True for a normal clone, a submodule, or a linked worktree.
    In submodules and worktrees .git is a file, not a directory, so asking
    git directly is more reliable than looking for a .git/ folder."""
    if not os.path.isdir(path):
        return False
    r = run(["git", "rev-parse", "--git-dir"], cwd=path)
    return r.returncode == 0


def git_pull(name, cfg, ff_only=True):
    print(f"  git pull origin {cfg['branch']}")
    if not is_git_repo(cfg["repo"]):
        raise RuntimeError(f"not a git repository: {cfg['repo']}")
    cmd = ["git", "pull"] + (["--ff-only"] if ff_only else []) + ["origin", cfg["branch"]]
    r = run(cmd, cwd=cfg["repo"])
    if r.returncode != 0:
        raise RuntimeError(f"git pull failed ({r.returncode}):\n{r.stderr.strip()}")
    print("  " + (r.stdout.strip() or r.stderr.strip()).splitlines()[0])


def find_source(name, cfg):
    """Resolve the .mot file, or discover the .srec inside a directory."""
    path = winpath(cfg["repo"], cfg["source"])

    tried = "\n".join(f"      {c}" for c in candidates(cfg["repo"], cfg["source"]))

    if cfg["kind"] == "mot":
        if not os.path.isfile(path):
            raise RuntimeError(
                "firmware image not found. Tried:\n" + tried +
                "\n    Run:  find " + cfg["repo"] + " -iname '*.mot'")
        return path

    if not os.path.isdir(path):
        raise RuntimeError(
            "build directory not found. Tried:\n" + tried +
            "\n    Run:  find " + cfg["repo"] + " -iname '*.srec'")
    matches = sorted(glob.glob(os.path.join(path, "*.srec")),
                     key=os.path.getmtime, reverse=True)
    if not matches:
        raise RuntimeError(f"no .srec file in:\n    {path}")
    if len(matches) > 1:
        print(f"  note: {len(matches)} .srec files found, using the newest")
        for m in matches[1:]:
            print(f"        ignoring {os.path.basename(m)}")
    return matches[0]


VERSION_RE = r"#define\s+VERSION_{field}_{build}\s+\(?\s*(\d+)\s*[Uu]?[Ll]?\s*\)?"


def parse_version_h(path):
    """Read VERSION_* macros from a version.h.

    Tolerates the real-world formatting motTohex.py's regex misses:
    multiple spaces, parentheses, and U/L integer suffixes -- e.g.
    "#define VERSION_MAJOR_DEV   (0U)".

    Returns (values, current_build) where values maps
    ("MAJOR","DEV") -> "0" and current_build is the DEV/TEST/MP named by
    CURRENT_BUILD_TYPE, or None if absent.
    """
    with open(path, "r", errors="replace") as f:
        text = f.read()

    values = {}
    for build in ("DEV", "TEST", "MP"):
        for field in ("MAJOR", "MINOR", "PATCH", "BUILD"):
            m = re.search(VERSION_RE.format(field=field, build=build), text)
            if m:
                values[(field, build)] = m.group(1)

    current = None
    m = re.search(r"#define\s+CURRENT_BUILD_TYPE\s+(DEV|TEST|MP)\b", text)
    if m:
        current = m.group(1)

    return values, current


def normalized_version_h(values, build, tmpdir):
    """Write a version.h in the exact plain format motTohex.py's regex wants."""
    major = values.get(("MAJOR", build))
    minor = values.get(("MINOR", build))
    if major is None or minor is None:
        raise RuntimeError(
            f"VERSION_MAJOR_{build} / VERSION_MINOR_{build} not found in version.h")

    path = os.path.join(tmpdir, "version_normalized.h")
    with open(path, "w") as f:
        f.write(f"#define VERSION_MAJOR_{build} {major}\n")
        f.write(f"#define VERSION_MINOR_{build} {minor}\n")
    return path, major, minor


def build_eterna(cfg, src, out, build_type):
    """Call motTohex.py <input.mot> <output.h> <version.h> <build_type>."""
    script = os.path.join(SCRIPTS_DIR, "motTohex.py")
    if not os.path.isfile(script):
        raise RuntimeError(f"motTohex.py not found in {SCRIPTS_DIR}")

    version_h = cfg["version_h"]
    if not os.path.isabs(version_h):
        version_h = winpath(cfg["repo"], version_h)
    if not os.path.isfile(version_h):
        raise RuntimeError(
            "Version.h not found — set PROJECTS['eterna']['version_h']:\n"
            f"    {version_h}")

    override = cfg.get("version_override")
    values, current = parse_version_h(version_h)

    # If the caller did not name a build type, follow CURRENT_BUILD_TYPE so the
    # header matches how the firmware was actually compiled.
    if build_type is None:
        if current is None:
            raise RuntimeError(
                "no --build given and CURRENT_BUILD_TYPE not found in version.h")
        build = current
        print(f"  build type: {build} (from CURRENT_BUILD_TYPE)")
    else:
        build = build_type.upper()
        if current and build != current:
            print(f"  WARNING: building {build} but version.h says "
                  f"CURRENT_BUILD_TYPE is {current}")
        else:
            print(f"  build type: {build}")

    if override:
        values = dict(values)
        values[("MAJOR", build)] = str(override["major"])
        values[("MINOR", build)] = str(override["minor"])

    with tempfile.TemporaryDirectory() as tmp:
        norm, major, minor = normalized_version_h(values, build, tmp)
        if override:
            print(f"  version: {major}.{minor} (pinned; version.h not used)")
        else:
            print(f"  version: {major}.{minor} ({build})")
        r = run([sys.executable, script, src, out, norm, build])
        # motTohex.py catches its own errors and exits 1 with "Error: ..."
        if r.returncode != 0 or not os.path.isfile(out):
            raise RuntimeError((r.stdout + r.stderr).strip() or "motTohex.py failed")
    return r.stdout.strip()


def build_lotier(src, out):
    """reneses_img_gen.py hardcodes output.srec -> reneses.bin in the cwd,
    so run it in a scratch directory with the input staged under that name."""
    script = os.path.join(SCRIPTS_DIR, "reneses_img_gen.py")
    if not os.path.isfile(script):
        raise RuntimeError(f"reneses_img_gen.py not found in {SCRIPTS_DIR}")

    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(script, os.path.join(tmp, "reneses_img_gen.py"))
        shutil.copy(src, os.path.join(tmp, "output.srec"))

        r = run([sys.executable, "reneses_img_gen.py"], cwd=tmp)
        produced = os.path.join(tmp, "reneses.bin")
        if r.returncode != 0 or not os.path.isfile(produced):
            raise RuntimeError((r.stdout + r.stderr).strip()
                               or "reneses_img_gen.py failed")

        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        shutil.move(produced, out)

    # sanity check: XMODEM packets are a whole number of 132-byte blocks
    size = os.path.getsize(out)
    if size % 132:
        print(f"  WARNING: {size} bytes is not a multiple of 132")
    return r.stdout.strip()


def compile_source(name, cfg):
    """Compile the firmware and return the freshly built image.

    Raises if the project has no compile config, so the caller can decide
    whether falling back to a checked-in artifact is acceptable.
    """
    if "compile" not in cfg:
        raise RuntimeError(f"no compile configuration for {name}")
    if compile_firmware is None:
        raise RuntimeError(
            f"compile_firmware.py must sit next to this script ({SCRIPTS_DIR})")
    return compile_firmware.compile_project(
        name, cfg["compile"], cfg["repo"],
        log=lambda m: print(f"  {m}"))


def build(name, cfg, build_type, do_pull=False, header=True, do_compile=True):
    if header:
        print(f"\n=== {name} ===")
    try:
        if do_pull:
            git_pull(name, cfg)

        if do_compile and "compile" in cfg:
            src = compile_source(name, cfg)
        else:
            src = find_source(name, cfg)
            if do_compile:
                print(f"  note: no compile config for {name}; "
                      "using the checked-in image")
        print(f"  source: {src}")

        out = resolve_output(cfg)

        if cfg["kind"] == "mot":
            log = build_eterna(cfg, src, out, build_type)
        else:
            log = build_lotier(src, out)

        for line in log.splitlines():
            print("  " + line)
        print(f"  output: {out}  ({os.path.getsize(out):,} bytes)")
        return True

    except Exception as e:
        print(f"  FAILED: {e}")
        return False


def main_list(names):
    """Print resolved paths for each project. Shared with pull_repos.py."""
    for n in names:
        cfg = PROJECTS[n]
        print(f"{n}:")
        print(f"  repo     {cfg['repo']}  [{cfg['branch']}]")
        c = cfg.get("compile")
        if c:
            print(f"  compile  {winpath(cfg['repo'], c['project'])}")
            print(f"           toolchain={c['toolchain']} "
                  f"target={c.get('make_target', 'all')} -> {c['artifact']}")
            dev = c.get("device_file")
            if dev:
                print(f"           device   {dev}"
                      f"{'' if os.path.isfile(dev) else '   *** MISSING ***'}")
        else:
            print("  compile  (none configured)")
        print(f"  source   {winpath(cfg['repo'], cfg['source'])}   "
              "(fallback, --no-compile)")
        if cfg["kind"] == "mot":
            print(f"  version  {winpath(cfg['repo'], cfg['version_h'])}")
        print(f"  output   {resolve_output(cfg)}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("names", nargs="*", metavar="PROJECT",
                   help="eterna and/or lotier (default: both)")
    p.add_argument("--pull", action="store_true", help="git pull before building")
    p.add_argument("--no-compile", action="store_true",
                   help="skip compiling; use the image checked into the repo")
    p.add_argument("--build", default=None, choices=["dev", "test", "mp"],
                   help="eterna version block to read "
                        "(default: follow CURRENT_BUILD_TYPE in version.h)")
    p.add_argument("--list", action="store_true", help="show resolved paths")
    args = p.parse_args()

    names = args.names or list(PROJECTS)
    unknown = [n for n in names if n not in PROJECTS]
    if unknown:
        p.error(f"unknown project(s): {', '.join(unknown)}. "
                f"Known: {', '.join(PROJECTS)}")

    if args.list:
        return main_list(names)

    results = [(n, build(n, PROJECTS[n], args.build, args.pull,
                         do_compile=not args.no_compile)) for n in names]
    failed = [n for n, ok in results if not ok]

    print(f"\n=== {len(results) - len(failed)}/{len(results)} succeeded ===")
    for n in failed:
        print(f"  failed: {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
