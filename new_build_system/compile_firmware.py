#!/usr/bin/env python3
"""Compile Renesas firmware from source, ahead of the image-conversion step.

    eterna   RL78/G16  R5F121BC     CC-RL             ->  DIY_Purifier.mot
    lotier   RA2E1     R7FA2E1A9    arm-none-eabi-gcc ->  RAseriesTEST1.srec

The e2 studio project trees were checked in from Windows machines and need a
set of fixups before they will build on Linux.  Those fixups are applied to a
COPY of the project under a work directory, never to the git checkout:

  * for the RL78 projects the .obj/.d files are tracked in git, so building
    in place would dirty the tree and make the next --ff-only pull fail;
  * it keeps a failed experiment from leaving the checkout in a odd state.

What gets fixed, and why:

  CC-RL (RL78)
    - stale .d files reference D:\\... and break make's dependency parsing
    - subcommand files use Windows paths and backslashes
    - -MAKEUD is an e2 studio-only option that standalone CC-RL rejects
    - -dev/-device must point at a device file that exists on this machine
    - a handful of objects have no subdir.mk rule at all and are compiled
      individually (see compile_missing_objects)

  arm-none-eabi-gcc (RA)
    - makefile.init exports a Windows PATH/TCINSTALL that must not be used
    - the link line carries a hardcoded -L "D:\\...\\script"
    - NONE of the subdir.mk fragments are committed, so they are regenerated
      from Debug/compile_commands.json
    - GCC 14 promoted several warnings to errors that GCC 13 (the reference
      toolchain) only warned about; those are demoted back so this build has
      the same semantics as the reference rather than silently rejecting code

  both
    - #include "Foo.h" that differs only in case from the real file, which is
      fine on Windows and fatal on Linux
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT = 1800

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import config

# GCC 14 turned these into hard errors; the reference build used GCC 13.2.1.
GCC14_COMPAT = (
    " -Wno-error=implicit-function-declaration"
    " -Wno-error=int-conversion"
    " -Wno-error=incompatible-pointer-types"
    " -Wno-error=implicit-int"
    " -Wno-error=return-mismatch"
    " -Wno-error=declaration-missing-parameter-type"
)


class CompileError(RuntimeError):
    pass


# --- small helpers --------------------------------------------------------

def _env():
    """Environment for toolchain invocations.

    The CC-RL bin directory is discovered rather than assumed, so the version
    number in its path (V1.16.00) is not baked in anywhere.
    """
    env = dict(os.environ)
    extra = [p for p in config.extra_tool_paths() if os.path.isdir(p)]
    if extra:
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(cmd, cwd, quiet=True):
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          env=_env(), timeout=TIMEOUT,
                          shell=isinstance(cmd, str))


def _tail(text, n=15):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    return "\n".join("      " + l for l in lines[-n:])


def _require(tool):
    if shutil.which(tool, path=_env()["PATH"]) is None:
        raise CompileError(
            f"{tool} not found on PATH.\n"
            f"      PATH searched: {_env()['PATH']}")


def sync_project(src, dst):
    """Mirror the project into the work directory."""
    src, dst = Path(src), Path(dst)
    if not src.is_dir():
        raise CompileError(f"project directory not found:\n      {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsync"):
        r = _run(["rsync", "-a", "--delete", f"{src}/", f"{dst}/"], cwd=dst.parent)
        if r.returncode != 0:
            raise CompileError(f"rsync failed:\n{_tail(r.stderr)}")
    else:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, symlinks=True)
    return dst


def casefix(root):
    """Symlink case-variant spellings of headers that sources #include.

    Windows is case-insensitive, Linux is not, so `#include "freertos.h"`
    against a real FreeRTOS.h compiles there and fails here.
    """
    root = Path(root)
    real = {}
    for p in root.rglob("*.h"):
        real.setdefault(p.name.lower(), p)

    includes = set()
    inc_re = re.compile(r'#include\s+"([^"]+)"')
    for pat in ("*.c", "*.h"):
        for f in root.rglob(pat):
            try:
                includes.update(inc_re.findall(f.read_text(errors="replace")))
            except OSError:
                pass

    made = []
    for inc in includes:
        name = os.path.basename(inc)
        target = real.get(name.lower())
        if target is None or target.name == name:
            continue
        link = target.with_name(name)
        if not link.exists():
            try:
                link.symlink_to(target.name)
                made.append(f"{link.relative_to(root)} -> {target.name}")
            except OSError:
                pass
    return made


def _rewrite_quoted_winpaths(text, project_name, new_root):
    """Repoint quoted Windows paths at the work directory.

    Only quoted strings are touched, so makefile line-continuation
    backslashes are left alone.
    """
    pat = re.compile(r'"([^"]*[A-Za-z]:[\\/][^"]*)"')

    def sub(m):
        p = m.group(1).replace("\\\\", "/").replace("\\", "/")
        idx = p.find("/" + project_name + "/")
        if idx != -1:
            p = str(new_root) + p[idx + len(project_name) + 1:]
        elif p.rstrip("/").endswith("/" + project_name):
            p = str(new_root)
        return '"' + p + '"'

    return pat.sub(sub, text)


# --- CC-RL / RL78 ---------------------------------------------------------

def fix_ccrl(proj, build_dir, cfg, log):
    proj, build_dir = Path(proj), Path(build_dir)
    project_name = proj.name
    notes = []

    device = cfg.get("device_file")
    if not device or not os.path.isfile(device):
        raise CompileError(
            "RL78 device file not found: "
            f"{cfg.get('device_file_name', '<unnamed>')}\n"
            f"      searched from workspace {config.WORKSPACE}\n"
            "      set HOAGS_DEVICE_FILE=/path/to/DR5F121BC.DVF, or put it in\n"
            f"      {config.WORKSPACE}/renesas-devicefiles/RL78/Common/\n"
            "      This file is required: without it rlink cannot resolve the\n"
            "      RAM mirror region and the link fails.  Extract it from an\n"
            "      e2 studio installer, e.g.\n"
            "        install/repos/rl78-supportfiles/plugins/\n"
            "          com.renesas.ide.supportfiles.rl78.devicefiles_*.jar\n"
            "            -> devicefiles_support.tar.xz -> RL78/Common/*.DVF")

    # 1. stale build artifacts from the Windows build
    removed = 0
    for pat in ("*.obj", "*.d"):
        for p in build_dir.rglob(pat):
            p.unlink()
            removed += 1
    if removed:
        notes.append(f"removed {removed} stale .obj/.d")

    # 2. subcommand files: no make syntax in these, so all backslashes are
    #    path separators and can be converted wholesale.
    for f in sorted(build_dir.rglob("*.tmp")):
        text = f.read_text(errors="replace").replace("\\", "/")
        text = re.sub(
            r'[A-Za-z]:/[^"\s]*?/' + re.escape(project_name) + r'(?=[/"])',
            str(proj), text)

        kept, had_dev, had_device = [], False, False
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("-MAKEUD="):
                continue          # e2 studio only; standalone CC-RL rejects it
            if s.startswith("-dev="):
                had_dev = True
                continue
            if s.startswith("-device="):
                had_device = True
                continue
            kept.append(line)

        # re-add pointing at the local device file, preserving which spelling
        # this particular subcommand file originally used
        if had_device:
            kept.insert(0, f'-device="{device}"')
        elif had_dev:
            kept.insert(0, f'-dev="{device}"')

        f.write_text("\n".join(kept) + "\n")

    # 3. makefiles: only the -subcommand="..." arguments carry backslashes
    for f in list(build_dir.rglob("*.mk")) + list(build_dir.rglob("makefile*")):
        if not f.is_file():
            continue
        text = f.read_text(errors="replace")
        text = re.sub(r'-subcommand="([^"]+)"',
                      lambda m: '-subcommand="%s"' % m.group(1).replace("\\", "/"),
                      text)
        f.write_text(text)

    links = casefix(proj)
    notes.extend(f"case-fix: {l}" for l in links)
    notes.append(f"device file: {device}")
    return notes


def _linker_subcommand(build_dir):
    """The linker subcommand file the makefile actually invokes."""
    mk = Path(build_dir) / "makefile"
    if mk.is_file():
        m = re.search(r'rlink\s+-subcommand="([^"]+)"', mk.read_text(errors="replace"))
        if m:
            p = Path(build_dir) / m.group(1).replace("\\", "/")
            if p.is_file():
                return p
    for p in sorted(Path(build_dir).glob("Linker*.tmp")):
        return p
    return None


def compile_missing_objects(proj, build_dir):
    """Compile objects the linker wants that no subdir.mk knows how to build.

    HardwareDebug/ is missing the generated makefile fragments for several
    source folders (src/dataflash/**, src/rfsp_lib/**), so make never builds
    them and the link fails on the first one.  They are compiled here with the
    project's standard C options.
    """
    proj, build_dir = Path(proj), Path(build_dir)
    sub = _linker_subcommand(build_dir)
    if sub is None:
        return []

    wanted = []
    for m in re.finditer(r'^-input="([^"]+)"', sub.read_text(errors="replace"), re.M):
        rel = re.sub(r"^\./", "", m.group(1).replace("\\", "/"))
        wanted.append(rel)

    built = []
    for rel in wanted:
        obj = build_dir / rel
        if obj.exists():
            continue
        src = proj / (rel[:-4] + ".c")
        if not src.is_file():
            continue                      # genuinely absent; let the linker say so

        # nearest available C subcommand file
        opts = build_dir / os.path.dirname(rel) / "cSubCommand.tmp"
        if not opts.is_file():
            opts = build_dir / "src" / "cSubCommand.tmp"
        if not opts.is_file():
            raise CompileError(f"no cSubCommand.tmp to compile {rel}")

        obj.parent.mkdir(parents=True, exist_ok=True)
        r = _run(["ccrl", f"-subcommand={opts.relative_to(build_dir)}",
                  "-msg_lang=english", "-o", str(obj.relative_to(build_dir)),
                  os.path.relpath(src, build_dir)], cwd=build_dir)
        if r.returncode != 0 or not obj.exists():
            raise CompileError(f"compiling {rel} failed:\n{_tail(r.stdout + r.stderr)}")
        built.append(rel)
    return built


def compile_ccrl(proj, cfg, log):
    build_dir = Path(proj) / cfg.get("build_subdir", "HardwareDebug")
    if not build_dir.is_dir():
        raise CompileError(f"build directory not found:\n      {build_dir}")
    _require("ccrl")
    _require("make")

    target = cfg.get("make_target", "all")

    # First pass builds everything that has a rule and then fails at the link
    # on the objects that do not.  Fill those in, then link.
    _run(["make", target], cwd=build_dir)

    extra = compile_missing_objects(proj, build_dir)
    if extra:
        log(f"compiled {len(extra)} object(s) with no makefile rule")

    r = _run(["make", target], cwd=build_dir)
    artifact = build_dir / cfg["artifact"]
    if r.returncode != 0 or not artifact.is_file():
        raise CompileError("make failed:\n" + _tail(r.stdout + r.stderr, 20))

    for extra_target in cfg.get("extra_targets", []):
        _run(["make", extra_target], cwd=build_dir)

    return artifact


# --- arm-none-eabi-gcc / RA -----------------------------------------------

def generate_subdir_mk(proj, build_dir, log):
    """Rebuild the subdir.mk fragments from compile_commands.json.

    None of them are committed, so without this OBJS is empty and the linker
    runs with nothing to link.
    """
    ccj = Path(build_dir) / "compile_commands.json"
    if not ccj.is_file():
        raise CompileError(
            "compile_commands.json not found -- it is the only record of the\n"
            f"      compile flags, and no subdir.mk files are committed:\n      {ccj}")

    entries = json.loads(ccj.read_text(errors="replace"))
    if not entries:
        raise CompileError("compile_commands.json is empty")

    win_root = entries[0]["directory"].replace("\\", "/").rstrip("/")

    by_dir, skipped = {}, []
    for e in entries:
        src = e["file"].replace("\\", "/")
        if src.startswith(win_root + "/"):
            src = src[len(win_root) + 1:]
        # linker scripts are listed too, with a bogus `clang` indexer command
        # containing unresolved ${workspace_loc} variables -- not build inputs
        if not src.endswith(".c"):
            skipped.append(os.path.basename(src))
            continue
        cmd = e["command"].replace("\\", "/").replace(win_root, str(proj))
        cmd = cmd.replace(" -c -o ", GCC14_COMPAT + " -c -o ", 1)
        by_dir.setdefault(os.path.dirname(src), []).append((src, cmd))

    if skipped:
        log("skipped non-compilation units: " + ", ".join(sorted(set(skipped))))

    total = 0
    for reldir, items in sorted(by_dir.items()):
        outdir = Path(build_dir) / reldir if reldir else Path(build_dir)
        outdir.mkdir(parents=True, exist_ok=True)

        srcs, objs, rules = [], [], []
        for src, cmd in sorted(items):
            base = os.path.splitext(os.path.basename(src))[0]
            obj = f"{reldir}/{base}.o" if reldir else f"{base}.o"
            srcs.append(f"../{src}")
            objs.append(f"./{obj}")
            rules.append(
                f"{obj}: ../{src}\n"
                f"\t@echo 'Building file: $<'\n"
                f"\t@mkdir -p $(dir $@)\n"
                f"\t@{cmd}\n")

        text = [
            "#" * 76,
            "# Regenerated from compile_commands.json -- the e2 studio originals",
            "# were never committed.  Flags are verbatim from the reference build,",
            "# plus -Wno-error=... to keep GCC 13 semantics under GCC 14.",
            "#" * 76,
            "",
            "C_SRCS += \\", " \\\n".join(srcs), "",
            "OBJS += \\", " \\\n".join(objs), "", "",
        ] + rules
        (outdir / "subdir.mk").write_text("\n".join(text))
        total += len(items)

    return len(by_dir), total


def fix_gcc_arm(proj, build_dir, cfg, log):
    proj, build_dir = Path(proj), Path(build_dir)
    notes = []

    # makefile.init exports a Windows PATH and TCINSTALL. Replace it, keeping
    # the original beside it for reference.
    init = build_dir / "makefile.init"
    if init.is_file():
        backup = build_dir / "makefile.init.windows.bak"
        if not backup.exists():
            shutil.copy2(init, backup)
        init.write_text(
            "# Replaced for Linux; original kept as makefile.init.windows.bak\n"
            "arg1 = $(1)\n"
            "export CWD=$(CURDIR)\n"
            "export PWD=$(CURDIR)\n")
        notes.append("neutralised makefile.init (Windows PATH/TCINSTALL)")

    # hardcoded -L "D:\...\script" and any other quoted Windows path
    mk = build_dir / "makefile"
    if mk.is_file():
        text = mk.read_text(errors="replace")
        fixed = _rewrite_quoted_winpaths(text, proj.name, proj)
        if fixed != text:
            mk.write_text(fixed)
            notes.append("rewrote Windows paths in makefile")

    dirs, files = generate_subdir_mk(proj, build_dir, log)
    notes.append(f"generated {dirs} subdir.mk covering {files} sources")

    notes.extend(f"case-fix: {l}" for l in casefix(proj))
    return notes


def compile_gcc_arm(proj, cfg, log):
    build_dir = Path(proj) / cfg.get("build_subdir", "Debug")
    if not build_dir.is_dir():
        raise CompileError(f"build directory not found:\n      {build_dir}")
    _require("arm-none-eabi-gcc")
    _require("make")

    artifact = build_dir / cfg["artifact"]
    # The committed Windows .elf/.srec are newer than their prerequisites, so
    # make would consider them up to date and do nothing at all -- which looks
    # exactly like a successful build.  Remove them first.
    stem = Path(cfg["artifact"]).stem
    for ext in (".elf", ".srec", ".map", ".sbd", ".elf.in"):
        p = build_dir / (stem + ext)
        if p.exists():
            p.unlink()
    for p in build_dir.rglob("*.o"):
        p.unlink()

    r = _run(["make", cfg.get("make_target", "all")], cwd=build_dir)
    if r.returncode != 0 or not artifact.is_file():
        raise CompileError("make failed:\n" + _tail(r.stdout + r.stderr, 20))
    return artifact


# --- entry point ----------------------------------------------------------

TOOLCHAINS = {
    # name -> (fixup, compile, default build subdirectory)
    "ccrl": (fix_ccrl, compile_ccrl, "HardwareDebug"),
    "gcc-arm": (fix_gcc_arm, compile_gcc_arm, "Debug"),
}


def compile_project(name, cfg, repo, workroot=None, log=print):
    """Compile one project from source. Returns the artifact path.

    cfg is PROJECTS[name]['compile'].
    """
    toolchain = cfg.get("toolchain")
    if toolchain not in TOOLCHAINS:
        raise CompileError(
            f"unknown toolchain {toolchain!r}; known: {', '.join(TOOLCHAINS)}")
    fixup, compile_fn, default_subdir = TOOLCHAINS[toolchain]

    # locate the project inside the repo, reusing build_firmware's resolver
    # if we were imported alongside it
    rel = cfg["project"]
    try:
        import build_firmware as bf
        src = bf.winpath(repo, rel)
    except Exception:
        src = os.path.join(repo, *[p for p in rel.replace("\\", "/").split("/") if p])
    if not os.path.isdir(src):
        raise CompileError(f"project not found in repo:\n      {src}")

    if workroot is None:
        parent = os.path.dirname(os.path.normpath(os.path.abspath(repo)))
        workroot = os.path.join(parent, "build", "compile")
    work = Path(workroot) / name / os.path.basename(os.path.normpath(src))

    log(f"toolchain: {toolchain}")
    log(f"work dir:  {work}")
    sync_project(src, work)

    build_dir = work / cfg.get("build_subdir", default_subdir)
    for note in fixup(work, build_dir, cfg, log):
        log(note)

    artifact = compile_fn(work, cfg, log)
    log(f"compiled:  {artifact}  ({artifact.stat().st_size:,} bytes)")
    return str(artifact)


if __name__ == "__main__":
    sys.exit("This module is used by build_firmware.py / pull_repos.py")
