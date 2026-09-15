# Renesas → HE3 build system

Builds the Renesas firmware from source, converts it to the deliverable, and
publishes it into the HE3 repo and build.

```
 git pull → compile → convert → stage into HE3 → push → build HE3

 eterna   RL78/G16  R5F121BCxFP   CC-RL     → .mot  → renesas_mot.h
 lotier   RA2E1     R7FA2E1A92    arm-gcc   → .srec → reneses.bin
```

Runs on any Linux machine. Nothing is hardcoded to a user or host.

---

## 1. Get the code

```bash
git clone <this repo> ~/renesas-he3-build
cd ~/renesas-he3-build
./setup.sh
```

`setup.sh` creates the directories, writes a `build-secrets.env` template,
and runs the health check. It changes nothing outside your workspace.

## 2. Install the toolchains

```bash
sudo apt install git make python3 rsync jq zip unzip gcc-arm-none-eabi
```

**RL78 (eterna only)** — Renesas CC-RL. Install the `.deb` from Renesas, then
check `ccrl` resolves. Free 60-day evaluation; after that `-Osize` silently
degrades to `-Olite` and code size changes, so a licence is needed for
production builds.

**The RL78 device file is mandatory and does not ship with the compiler.**
Without `DR5F121BC.DVF`, rlink cannot resolve the RAM mirror region and the
link fails — there is no workaround. Get it from an e2 studio installer
(the Linux `.run` is a Makeself archive, so you do not have to install it):

```bash
./e2studio_installer-*.run --noexec --keep --target /tmp/e2s
cd /tmp/e2s/install/repos/rl78-supportfiles/plugins
unzip -o com.renesas.ide.supportfiles.rl78.devicefiles_*.jar devicefiles_support.tar.xz
tar xf devicefiles_support.tar.xz
mkdir -p ~/renesas-devicefiles/RL78/Common
cp RL78/Common/DR5F121BC.DVF ~/renesas-devicefiles/RL78/Common/
```

It is then found automatically. Also worth grabbing while you are in there —
needed for the RL78 `.x` debug output:

```bash
cd /tmp/e2s/install/repos/rl78-supportfiles/plugins
unzip -o com.renesas.ide.supportfiles.rl78.ccrl.build.linux.x86_64_*.jar utils_support.tar.xz
tar xf utils_support.tar.xz && mkdir -p ~/.local/bin
cp renesas_cc_converter rl78-elf-objcopy ~/.local/bin/
```

**RA / HE3** use the distro `arm-none-eabi-gcc`. Note GCC 14+ is stricter
than the 13.2 the projects were written against; the build passes
`-Wno-error=...` to keep the original behaviour rather than silently
changing what compiles.

## 3. Clone the firmware repos

Into your workspace (default `$HOME`):

```bash
git clone -b Eterna_automation https://github.com/hoagstech/External ~/eterna_automation/External
git clone -b Lotier_automation https://github.com/hoagstech/External ~/lotier_automation/External
```

## 4. Add your credentials

Edit `~/build-secrets.env` (created by `setup.sh`, chmod 600):

```bash
HOAGS_GIT_TOKEN=ghp_your_own_token
HOAGS_GIT_USER=your-github-username
```

Use **your own** personal access token with repo scope — do not share one.
The token is only ever read from this file; it is never written into a git
remote URL, so it will not end up in `.git/config`.

## 5. Check and run

```bash
cd new_build_system
./hoags-build doctor        # tells you exactly what is still missing
./hoags-build firmware      # pull + compile + convert
```

`doctor` exits non-zero if anything required is absent, so it can gate a
provisioning script.

---

## Commands

| command | does |
|---|---|
| `./hoags-build doctor` | check the machine, print every resolved path |
| `./hoags-build list` | show what would be used, change nothing |
| `./hoags-build firmware [P]` | pull + compile + convert |
| `./hoags-build release [P]` | + stage into a local HE3 checkout (no push) |
| `./hoags-build he3 [P]` | + push to HE3 and run the HE3 build |

`P` is `eterna` and/or `lotier`; omit for both.

Useful flags: `--no-pull`, `--no-compile`, `--skip-firmware`,
`--build-type dev|test|mp`, `--ci` (use the shared `build.sh`, which also
uploads to S3 and rewrites the OTA manifest — **off by default**).

`release` and `he3` write to shared branches. `he3` also pushes, because the
HE3 build does `git reset --hard origin/<branch>` and would otherwise build
without your artifact. Start with `firmware` or `release` if you are unsure.

## Configuration

Everything hangs off one setting:

```bash
export HOAGS_WORKSPACE=/srv/builds     # default: $HOME
```

Expected layout:

```
$HOAGS_WORKSPACE/
  eterna_automation/External/   git checkout, branch Eterna_automation
  lotier_automation/External/   git checkout, branch Lotier_automation
  build-secrets.env             credentials, chmod 600
  renesas-devicefiles/          RL78 *.DVF
```

Anything else is created on demand. For a different layout, copy
`new_build_system/config.ini.example` to `config.ini` and set paths
individually. Precedence: **environment > config.ini > default**.

## Layout

```
new_build_system/    pipeline: config, compile, convert, publish
new_build_script/    isolated HE3 build (replaces the old build-scripts)
```

Keep them siblings; the first locates the second relative to itself.

## Notes for reviewers

The e2 studio projects were authored on Windows and need fixups before they
build on Linux — Windows paths in generated makefiles, options the
standalone compiler rejects, case-sensitive `#include`s, and missing
`subdir.mk` fragments (the RA project ships none of its 20). These are
applied to a **copy** under `<repo>/build/compile/`, never to your git
checkout: the RL78 projects track their own `.obj`/`.d` files, so building
in place would dirty the tree and break the next `--ff-only` pull.

Known issues in the firmware source, deliberately not papered over:

- **`hal_entry.c` calls `APP_PRINT` without including `common_utilis.h`.** It
  links only because `--gc-sections` discards the unreferenced function.
- **The RA build path is embedded in flash** via FreeRTOS `configASSERT`
  and `__FILE__`. Builds are reproducible, but relocating the workspace
  changes the image.
- **CC-RL evaluation licence** as above.
