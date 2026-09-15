#!/usr/bin/env python3
"""Publish freshly built Renesas artifacts into the HE3 repo and build HE3.

Pipeline, per project:

    1. build_firmware.py   pull + compile + convert   (optional, --skip-firmware)
    2. checkout            hoagstech/HE3 at the project's branch
    3. replace             the Renesas artifact in that checkout
    4. commit
    5. push                                            (--push)
    6. HE3 build           build.sh with the CI keys   (--build)

    eterna  -> branch ETERNA_AUTOMATION
               renesas_firmware.h -> .../sensors/Renesas/include/renesas_mot.h
    lotier  -> branch LOTIER_BUILD_AUTOMATION
               reneses.bin        -> sdk-ameba-v7.1d/Hoags/reneses.bin

Why the push has to happen before the build: funcs.sh getCode() does a
`git reset --hard origin/$GITBRANCH` followed by `git clean -fd`, so anything
staged only locally in the build checkout is destroyed before make runs.  The
artifact reaches the build solely by way of the remote branch.

Stages 5 and 6 are opt-in.  They write to a shared branch, and the build tail
uploads to S3 and rewrites the OTA manifest for a real device MAC.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import config
import build_firmware as bf

# --- configuration --------------------------------------------------------

HE3_OWNER = config.HE3_OWNER
HE3_NAME = config.HE3_REPO

# Where the HE3 working checkouts live (one per branch).
WORKROOT = config.HE3_WORKROOT

# Repo whose remote carries the token to reuse. Any configured project will
# do; the first one with a token embedded in its origin URL wins.
TOKEN_SOURCE_REPOS = [c["repo"] for c in bf.PROJECTS.values()]

# Which artifact goes where, per project.
TARGETS = {
    "eterna": {
        "branch": "ETERNA_AUTOMATION",
        "files": [{
            # build_firmware.py's 'output' for this project
            "artifact": "output",
            "dest": "sdk-ameba-v7.1d/project/realtek_amebaz2_v0_example/src/"
                    "hoags/sensors/Renesas/include/renesas_mot.h",
        }],
    },
    "lotier": {
        "branch": "LOTIER_BUILD_AUTOMATION",
        "files": [{
            "artifact": "output",
            "dest": "sdk-ameba-v7.1d/Hoags/reneses.bin",
        }],
        # The firmware carries the reneses.bin geometry as compile-time
        # constants, so they have to track the new image or the device will
        # transfer the wrong number of XMODEM rows.
        "row_size_header": {
            "path": "sdk-ameba-v7.1d/project/realtek_amebaz2_v0_example/src/"
                    "hoags/device_controls/purifier/include/remoteDiag.h",
            "column_define": "COLUMN_SIZE",
            "row_define": "TOTAL_ROW_SIZE",
        },
    },
}

# Isolated HE3 build system: self-contained vars/funcs/entry point, so this
# pipeline neither reads nor modifies the shared build-scripts tree.
BUILD_SCRIPTS_DIR = config.HE3_SCRIPTS
BUILD_ENTRY = "build_he3.sh"

# The shared tree, used only with --ci (full build.sh incl. S3 + OTA manifest).
LEGACY_SCRIPTS_DIR = config.LEGACY_SCRIPTS
LEGACY_ENTRY = "build.sh"

SECRETS_FILE = config.SECRETS_FILE

TIMEOUT = 3600
# --------------------------------------------------------------------------


class ReleaseError(RuntimeError):
    pass


def redact(text, token):
    if not text:
        return ""
    out = text.replace(token, "***") if token else text
    return re.sub(r"(https://)[^@\s]+@", r"\1***@", out)


def run(cmd, cwd=None, token=None, check=True, env=None, stream=False):
    if env is None:
        env = config.git_env()      # GIT_ASKPASS; no token in any URL
    if stream:
        p = subprocess.run(cmd, cwd=cwd, env=env, timeout=TIMEOUT)
        if check and p.returncode != 0:
            raise ReleaseError(f"command failed ({p.returncode}): {cmd[0]}")
        return p
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       env=env, timeout=TIMEOUT)
    if check and p.returncode != 0:
        raise ReleaseError(
            f"command failed ({p.returncode}): {' '.join(cmd[:3])}\n"
            + redact((p.stdout or "") + (p.stderr or ""), token))
    return p


def get_token():
    """GitHub token from the environment or the secrets file.

    Tokens are deliberately not read out of remote URLs any more: storing one
    in .git/config leaves it in plaintext in every clone.
    """
    tok = config.git_token()
    if tok:
        return tok

    # Fall back to a token embedded in a remote, but say so -- it should be
    # moved into the secrets file.
    for repo in TOKEN_SOURCE_REPOS:
        if not os.path.isdir(repo):
            continue
        p = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo,
                           capture_output=True, text=True)
        if p.returncode == 0:
            m = re.match(r"https://([^@/]+)@", p.stdout.strip())
            if m:
                print(f"  WARNING: using a token embedded in {repo}/.git/config."
                      f"\n           Move it to {config.SECRETS_FILE} as "
                      "HOAGS_GIT_TOKEN and strip it from the remote.")
                return m.group(1).split(":")[-1]

    raise ReleaseError(
        "no github token. Add HOAGS_GIT_TOKEN to "
        f"{config.SECRETS_FILE}\n      (chmod 600), or export it.")


def he3_url(token=None):
    """Clean remote URL. Credentials come from GIT_ASKPASS, so the token is
    never written into .git/config or visible in `git remote -v`."""
    return f"https://github.com/{HE3_OWNER}/{HE3_NAME}"


def checkout(branch, token, log):
    """Shallow single-branch checkout of HE3 at `branch`, refreshed in place."""
    dest = os.path.join(WORKROOT, branch)
    url = he3_url(token)
    os.makedirs(WORKROOT, exist_ok=True)

    if os.path.isdir(os.path.join(dest, ".git")):
        log(f"refreshing {dest}")
        run(["git", "remote", "set-url", "origin", url], cwd=dest, token=token)
        run(["git", "fetch", "--depth", "1", "origin", branch], cwd=dest, token=token)
        run(["git", "checkout", "-B", branch, "FETCH_HEAD"], cwd=dest, token=token)
        run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=dest, token=token)
        run(["git", "clean", "-fd"], cwd=dest, token=token)
    else:
        log(f"cloning {HE3_OWNER}/{HE3_NAME} [{branch}] -> {dest}")
        run(["git", "clone", "--depth", "1", "--single-branch",
             "--branch", branch, url, dest], token=token)

    sha = run(["git", "rev-parse", "HEAD"], cwd=dest, token=token).stdout.strip()
    log(f"at {sha[:8]}")
    return dest


def replace_files(name, cfg, checkout_dir, log):
    """Copy the built artifacts over their counterparts in the HE3 checkout."""
    changed = []
    for spec in TARGETS[name]["files"]:
        if spec["artifact"] != "output":
            raise ReleaseError(f"unknown artifact key {spec['artifact']!r}")
        src = bf.resolve_output(cfg)
        if not os.path.isfile(src):
            raise ReleaseError(
                f"built artifact missing:\n      {src}\n"
                "      run without --skip-firmware, or build it first")

        dst = os.path.join(checkout_dir, *spec["dest"].split("/"))
        if not os.path.isfile(dst):
            raise ReleaseError(
                "target file not present on this branch:\n"
                f"      {spec['dest']}\n"
                f"      branch: {TARGETS[name]['branch']}")

        old = os.path.getsize(dst)
        same = (open(dst, "rb").read() == open(src, "rb").read())
        shutil.copyfile(src, dst)
        log(f"{spec['dest']}")
        log(f"    {old:,} -> {os.path.getsize(dst):,} bytes"
            + ("   (identical content)" if same else ""))
        if not same:
            changed.append(spec["dest"])
    return changed


def update_row_size(name, cfg, checkout_dir, log):
    """Point TOTAL_ROW_SIZE at the new reneses.bin.

    reneses.bin is a stream of fixed-width XMODEM rows; the firmware needs to
    know how many there are.  COLUMN_SIZE is read from the header rather than
    assumed, and the image must divide by it exactly -- a remainder means the
    two have diverged and is treated as an error rather than rounded away.
    """
    spec = TARGETS[name].get("row_size_header")
    if not spec:
        return

    path = os.path.join(checkout_dir, *spec["path"].split("/"))
    if not os.path.isfile(path):
        raise ReleaseError(f"row-size header not found:\n      {spec['path']}")

    artifact = bf.resolve_output(cfg)
    size = os.path.getsize(artifact)
    # newline='' so the file's existing CRLF endings survive the rewrite --
    # otherwise every line shows as modified and the diff buries the one
    # value that actually changed.
    with open(path, "r", newline="") as fh:
        text = fh.read()

    col_re = re.compile(r"^(\s*#define\s+%s\s+)(\d+)" % spec["column_define"], re.M)
    row_re = re.compile(r"^(\s*#define\s+%s\s+)(\d+)" % spec["row_define"], re.M)

    mcol, mrow = col_re.search(text), row_re.search(text)
    if not mcol or not mrow:
        raise ReleaseError(
            f"{spec['column_define']} / {spec['row_define']} not found in "
            f"{spec['path']}")

    column = int(mcol.group(2))
    old_rows = int(mrow.group(2))

    if size % column:
        raise ReleaseError(
            f"{os.path.basename(artifact)} is {size:,} bytes, not a whole "
            f"number of {column}-byte rows ({size / column:.2f}).")
    rows = size // column

    if rows == old_rows:
        log(f"{spec['row_define']} already {rows}")
        return

    with open(path, "w", newline="") as fh:
        fh.write(row_re.sub(lambda m: m.group(1) + str(rows), text, count=1))
    log(f"{spec['path'].split('/')[-1]}")
    log(f"    {spec['row_define']} {old_rows} -> {rows}"
        f"   ({size:,} bytes / {column})")


def commit(checkout_dir, message, token, log):
    st = run(["git", "status", "--porcelain"], cwd=checkout_dir, token=token)
    if not st.stdout.strip():
        log("nothing to commit -- HE3 already has these bytes")
        return None
    for line in st.stdout.strip().splitlines():
        log(f"  {line}")
    run(["git", "add", "-A"], cwd=checkout_dir, token=token)
    run(["git", "commit", "-m", message], cwd=checkout_dir, token=token)
    sha = run(["git", "rev-parse", "HEAD"], cwd=checkout_dir, token=token).stdout.strip()
    log(f"committed {sha[:8]}")
    return sha


def push(checkout_dir, branch, token, log):
    log(f"pushing to {HE3_OWNER}/{HE3_NAME} {branch}")
    p = run(["git", "push", "origin", f"HEAD:{branch}"],
            cwd=checkout_dir, token=token)
    log(redact((p.stdout + p.stderr).strip(), token) or "pushed")


def he3_build(branch, token, args, log):
    """Build HE3 from hoagstech/HE3 at `branch`.

    Runs the isolated ~/new_build_script/build_he3.sh: the same stages as the
    original build.sh up to copyBuild, without the S3 upload / OTA manifest
    rewrite / version bump. Pass --ci to use the shared build.sh instead.

    The isolated vars_he3.sh takes the repository owner from GITHUBORG rather
    than assuming it equals GITUSER, so the token's account and the repo
    owner can differ. With --ci the shared varsHE3.sh is used, which has no
    GITHUBORG, so GITUSER has to be overridden instead.
    """
    if not os.path.isfile(SECRETS_FILE):
        raise ReleaseError(f"secrets file not found: {SECRETS_FILE}")

    if args.ci:
        scripts_dir, script = LEGACY_SCRIPTS_DIR, LEGACY_ENTRY
    else:
        scripts_dir, script = BUILD_SCRIPTS_DIR, BUILD_ENTRY
    if not os.path.isfile(os.path.join(scripts_dir, script)):
        raise ReleaseError(f"{script} not found in {scripts_dir}")

    # The token is passed through the environment, never on the command line,
    # so it cannot leak into `ps` output or a build log.
    env = dict(os.environ)
    env["HE3_PUSH_TOKEN"] = token

    cmd = [
        "bash", "-c",
        # secrets first (AWS creds, CI_TEST_MAC, ...), then override the repo
        # coordinates so the build pulls the branch we just pushed to.
        f'set -a; source "{SECRETS_FILE}"; set +a; '
        f'export GITHUBORG="{HE3_OWNER}" HOAGS_GIT_TOKEN="$HE3_PUSH_TOKEN" '
        f'GITTOKEN="$HE3_PUSH_TOKEN" '   # --ci path still reads GITTOKEN
        # --ci uses the shared varsHE3.sh, which builds the URL from GITUSER
        # and ignores GITHUBORG; set both so either entry point resolves to
        # the same repository.
        f'GITUSER="{HE3_OWNER}" '
        f'CHECKOUTPATH="{args.checkout_path}" '
        # keep the shell side on exactly the paths config.py resolved
        f'HOAGS_WORKSPACE="{config.WORKSPACE}" '
        f'TARGETIMAGEPATH="{config.BUILD_OUTPUT}"; '
        f'cd "{scripts_dir}" && bash {script} '
        f'--flashsize {args.flashsize} --type {args.type} '
        f'--customer {args.customer} --board {args.board} --sha {args.sha} '
        f'--loglevel {args.loglevel} --capability {args.capability} '
        f'--securedImg {args.secured_img} --securedSoc {args.secured_soc} '
        f'--uartLogDisable {args.uart_log_disable} '
        f'--filterSetting {args.filter_setting} '
        f'--model {args.model} --branch {branch} '
        f'--note "{args.note}"'
    ]
    log("starting HE3 build (streaming output)")
    run(cmd, env=env, stream=True)


def release(name, args, token, log):
    cfg = bf.PROJECTS[name]
    branch = TARGETS[name]["branch"]
    log(f"HE3 branch: {branch}")

    if not args.skip_firmware:
        ok = bf.build(name, cfg, args.build_type, do_pull=not args.no_pull,
                      header=False, do_compile=not args.no_compile)
        if not ok:
            raise ReleaseError("firmware build failed; not touching HE3")
    else:
        log(f"using existing artifact: {bf.resolve_output(cfg)}")

    work = checkout(branch, token, log)
    changed = replace_files(name, cfg, work, log)
    update_row_size(name, cfg, work, log)

    msg = args.message or (
        f"{name}: update Renesas artifact from automated build\n\n"
        + "\n".join(f"- {c}" for c in changed))
    sha = commit(work, msg, token, log)

    if args.push:
        if sha is None:
            log("skipping push -- no new commit")
        else:
            push(work, branch, token, log)
    elif sha:
        log("NOT pushed (--push to publish). The HE3 build resets to")
        log("origin/<branch>, so it will not see this until it is pushed.")

    if args.build:
        he3_build(branch, token, args, log)

    return True


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("names", nargs="*", metavar="PROJECT",
                   help=f"any of: {', '.join(TARGETS)} (default: all)")
    p.add_argument("--skip-firmware", action="store_true",
                   help="reuse the existing built artifact")
    p.add_argument("--no-pull", action="store_true",
                   help="do not git pull the firmware repo")
    p.add_argument("--no-compile", action="store_true",
                   help="convert the checked-in image instead of compiling")
    p.add_argument("--build-type", default=None, choices=["dev", "test", "mp"],
                   help="eterna version block")
    p.add_argument("--message", default=None, help="commit message")

    p.add_argument("--push", action="store_true",
                   help="push the commit to the HE3 branch")
    p.add_argument("--build", action="store_true",
                   help="run the HE3 build; implies --push, because the build "
                        "hard-resets to origin/<branch> and would otherwise "
                        "build without the new artifact")
    p.add_argument("--ci", action="store_true",
                   help="use the full build.sh, which also uploads the OTA to "
                        "S3 and rewrites the manifest for CI_TEST_MAC "
                        "(default: build_only.sh, images only)")
    p.add_argument("--list", action="store_true", help="show what would happen")

    b = p.add_argument_group("HE3 build parameters (build.sh)")
    b.add_argument("--checkout-path", default=config.HE3_CHECKOUT,
                   help="where HE3 is cloned and built; reset --hard and "
                        "clean -fd on every run, so never point this at a "
                        "tree anyone edits by hand")
    b.add_argument("--flashsize", default="4MB")
    b.add_argument("--type", default="dev", dest="type")
    b.add_argument("--customer", default="LIVPURE_PURIFIER")
    b.add_argument("--board", default="he3")
    b.add_argument("--sha", default="HEAD")
    b.add_argument("--loglevel", default="1")
    b.add_argument("--capability", default="4")
    b.add_argument("--secured-img", default="0")
    b.add_argument("--secured-soc", default="0")
    b.add_argument("--uart-log-disable", default="0")
    b.add_argument("--filter-setting", default="0")
    b.add_argument("--model", default="TEST001")
    b.add_argument("--note", default="automated Renesas artifact update")
    args = p.parse_args()

    # The build hard-resets to origin/<branch>, so building without pushing
    # would silently build the old artifact.
    if args.build:
        args.push = True

    names = args.names or list(TARGETS)
    unknown = [n for n in names if n not in TARGETS]
    if unknown:
        p.error(f"unknown project(s): {', '.join(unknown)}. "
                f"Known: {', '.join(TARGETS)}")

    if args.list:
        for n in names:
            t = TARGETS[n]
            print(f"{n}:")
            print(f"  he3 branch  {HE3_OWNER}/{HE3_NAME}  [{t['branch']}]")
            print(f"  artifact    {bf.resolve_output(bf.PROJECTS[n])}")
            for f in t["files"]:
                print(f"  replaces    {f['dest']}")
            print(f"  checkout    {os.path.join(WORKROOT, t['branch'])}")
        return 0

    token = get_token()

    results = []
    for n in names:
        print(f"\n{'=' * 64}\n{n}\n{'=' * 64}")
        try:
            results.append((n, release(n, args, token, lambda m: print(f"  {m}"))))
        except Exception as e:
            print(f"  FAILED: {redact(str(e), token)}")
            results.append((n, False))

    failed = [n for n, ok in results if not ok]
    print(f"\n{'=' * 64}")
    print(f"{len(results) - len(failed)}/{len(results)} succeeded")
    for n in failed:
        print(f"  failed: {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
