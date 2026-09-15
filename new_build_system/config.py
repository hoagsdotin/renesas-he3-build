#!/usr/bin/env python3
"""Path and tool resolution for the Renesas/HE3 build system.

Nothing in this system hardcodes an absolute path. Every location is resolved
here, in this order:

    1. an environment variable          HOAGS_WORKSPACE, HOAGS_DEVICE_FILE, ...
    2. a config file                    see CONFIG_SEARCH below
    3. a default derived from WORKSPACE, or auto-discovered on disk

WORKSPACE is the one thing worth setting: it is the directory holding the
project checkouts (eterna_automation/, lotier_automation/, ...). It defaults
to $HOME, which matches the usual layout, and can be pointed anywhere.

    export HOAGS_WORKSPACE=/srv/builds

Run `python3 doctor.py` to see everything resolved, and what is missing.
"""

import configparser
import glob
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

# Config file, first match wins.
CONFIG_SEARCH = [
    os.environ.get("HOAGS_BUILD_CONFIG", ""),
    os.path.join(HERE, "config.ini"),
    os.path.expanduser("~/.config/hoags-build/config.ini"),
    "/etc/hoags-build/config.ini",
]

# Where a CC-RL install might live. Globs, newest version last.
CCRL_GLOBS = [
    "/usr/local/Renesas/CC-RL/*/bin",
    "/opt/Renesas/CC-RL/*/bin",
    "/opt/renesas/cc-rl/*/bin",
    "~/Renesas/CC-RL/*/bin",
]

# Where RL78 device files (*.DVF) might live.
DEVICE_FILE_GLOBS = [
    "{workspace}/renesas-devicefiles/**/{name}",
    "/usr/local/Renesas/DeviceFiles/**/{name}",
    "/opt/Renesas/DeviceFiles/**/{name}",
    "~/.eclipse/**/DebugComp/RL78/RL78/Common/{name}",
    "~/e2_studio/**/{name}",
]


def _load_env_file(path):
    """Read KEY=VALUE lines into os.environ without overwriting real env vars.

    Lets secrets and settings live in one file (build-secrets.env) instead of
    being embedded in git remote URLs or exported by hand. Anything already
    set in the environment wins, so a caller can still override.
    """
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path) as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        return False
    return True


def _read_config():
    cp = configparser.ConfigParser()
    for path in CONFIG_SEARCH:
        if path and os.path.isfile(path):
            cp.read(path)
            cp.loaded_from = path
            return cp
    cp.loaded_from = None
    return cp


_CFG = _read_config()


def _expand(p):
    if not p:
        return p
    return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))


def setting(env_var, section, key, default=""):
    """Environment variable, then config file, then default."""
    val = os.environ.get(env_var)
    if val:
        return val
    if _CFG.has_option(section, key):
        val = _CFG.get(section, key)
        if val:
            return val
    return default


# --- the one root everything else hangs off -------------------------------

WORKSPACE = _expand(setting("HOAGS_WORKSPACE", "paths", "workspace", "~"))

CONFIG_FILE = getattr(_CFG, "loaded_from", None)


def in_workspace(*parts):
    return os.path.join(WORKSPACE, *parts)


# --- discovery ------------------------------------------------------------

def find_ccrl_bin():
    """Directory containing ccrl/rlink, or None."""
    explicit = setting("HOAGS_CCRL_BIN", "tools", "ccrl_bin")
    if explicit:
        return _expand(explicit)

    on_path = shutil.which("ccrl")
    if on_path:
        return os.path.dirname(os.path.realpath(on_path))

    found = []
    for pattern in CCRL_GLOBS:
        found.extend(glob.glob(os.path.expanduser(pattern)))
    found = [d for d in sorted(found) if os.path.isfile(os.path.join(d, "ccrl"))]
    return found[-1] if found else None


def find_device_file(name):
    """Locate an RL78 device file such as DR5F121BC.DVF, or None.

    Required by CC-RL: without it rlink cannot resolve the RAM mirror region
    and the link fails. Extract it from an e2 studio installer:
      install/repos/rl78-supportfiles/plugins/
        com.renesas.ide.supportfiles.rl78.devicefiles_*.jar
          -> devicefiles_support.tar.xz -> RL78/Common/*.DVF
    """
    explicit = setting("HOAGS_DEVICE_FILE", "tools", "device_file")
    if explicit:
        return _expand(explicit)

    for pattern in DEVICE_FILE_GLOBS:
        p = os.path.expanduser(pattern.format(workspace=WORKSPACE, name=name))
        hits = sorted(glob.glob(p, recursive=True))
        if hits:
            return hits[0]
    return None


def extra_tool_paths():
    """Directories to prepend to PATH when running a toolchain."""
    paths = []
    ccrl = find_ccrl_bin()
    if ccrl:
        paths.append(ccrl)
    for extra in (setting("HOAGS_TOOL_PATHS", "tools", "extra_paths", ""),
                  "~/.local/bin"):
        for part in extra.split(os.pathsep):
            part = _expand(part.strip())
            if part and os.path.isdir(part) and part not in paths:
                paths.append(part)
    return paths


# --- resolved locations ---------------------------------------------------

def project_repo(name, default_dir):
    """Git checkout for a firmware project."""
    return _expand(setting(f"HOAGS_{name.upper()}_REPO", "projects", name,
                           in_workspace(default_dir)))


SECRETS_FILE = _expand(setting(
    "HOAGS_SECRETS", "paths", "secrets", in_workspace("build-secrets.env")))

# Load it now, so HOAGS_* defined there is visible to everything below and to
# every module that imports config. Real environment variables still win.
SECRETS_LOADED = _load_env_file(SECRETS_FILE)


def git_token():
    """GitHub token, from the environment / secrets file. Never from a URL."""
    for var in ("HOAGS_GIT_TOKEN", "HOAGS_HE3_TOKEN", "HE3_TOKEN"):
        val = os.environ.get(var)
        if val:
            return val
    return None


def git_user():
    return os.environ.get("HOAGS_GIT_USER") or HE3_OWNER


ASKPASS = os.path.join(HERE, "git-askpass.sh")


def git_env(base=None):
    """Environment that lets git authenticate without a token in the URL.

    GIT_ASKPASS feeds the token from the environment, so remotes stay clean
    (https://github.com/org/repo) and nothing is written to .git/config.
    """
    env = dict(base or os.environ)
    token = git_token()
    if token:
        env["HOAGS_GIT_TOKEN"] = token
        env["HOAGS_GIT_USER"] = git_user()
        if os.path.isfile(ASKPASS):
            env["GIT_ASKPASS"] = ASKPASS
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env

# HE3 working clones, one per branch, used to stage and push artifacts.
HE3_WORKROOT = _expand(setting(
    "HOAGS_HE3_WORKROOT", "paths", "he3_workroot", in_workspace("he3-release")))

# HE3 build checkout. reset --hard + clean -fd every run.
HE3_CHECKOUT = _expand(setting(
    "HOAGS_HE3_CHECKOUT", "paths", "he3_checkout", in_workspace("he3-build")))

# Isolated HE3 build scripts. Sibling of this directory by default.
HE3_SCRIPTS = _expand(setting(
    "HOAGS_HE3_SCRIPTS", "paths", "he3_scripts",
    os.path.join(os.path.dirname(HERE), "new_build_script")))

# Optional: the older shared build-scripts tree, only used by --ci.
LEGACY_SCRIPTS = _expand(setting(
    "HOAGS_LEGACY_SCRIPTS", "paths", "legacy_scripts",
    in_workspace("build-scripts")))

BUILD_OUTPUT = _expand(setting(
    "HOAGS_OUTPUT", "paths", "output", in_workspace("http-server/local/he3")))

LOG_DIR = _expand(setting("HOAGS_LOG_DIR", "paths", "logs",
                          in_workspace("build-logs")))

HE3_OWNER = setting("HOAGS_HE3_OWNER", "he3", "owner", "hoagstech")
HE3_REPO = setting("HOAGS_HE3_REPO", "he3", "repo", "HE3")


def summary():
    """(label, value, ok) rows for doctor.py."""
    rows = [
        ("config file", CONFIG_FILE or "(none; defaults + env)", True),
        ("workspace", WORKSPACE, os.path.isdir(WORKSPACE)),
        ("secrets", SECRETS_FILE, os.path.isfile(SECRETS_FILE)),
        ("he3 scripts", HE3_SCRIPTS, os.path.isdir(HE3_SCRIPTS)),
        ("he3 workroot", HE3_WORKROOT, True),
        ("he3 checkout", HE3_CHECKOUT, True),
        ("build output", BUILD_OUTPUT, True),
        ("log dir", LOG_DIR, True),
        ("he3 repo", f"{HE3_OWNER}/{HE3_REPO}", True),
    ]
    ccrl = find_ccrl_bin()
    rows.append(("ccrl bin", ccrl or "NOT FOUND", bool(ccrl)))
    return rows
