# Renesas → HE3 build system

Compiles Renesas firmware from source, converts it to the deliverable, and
publishes it into the HE3 repo and build.

```
  git pull  →  compile  →  convert  →  stage into HE3  →  push  →  build HE3

  eterna   RL78/G16  R5F121BC   CC-RL     → .mot  → renesas_mot.h
  lotier   RA2E1     R7FA2E1A9  arm-gcc   → .srec → reneses.bin
```

## Quick start

```bash
./hoags-build doctor        # check the machine, show every resolved path
./hoags-build firmware      # pull + compile + convert, both projects
./hoags-build he3 lotier    # ...then stage into HE3, push, and build HE3
```

`doctor` exits non-zero if anything required is missing, so it can gate a
provisioning script.

## Running on another machine

Nothing is hardcoded to a user or host. Everything hangs off one setting:

```bash
export HOAGS_WORKSPACE=/srv/builds     # default: $HOME
./hoags-build doctor
```

The workspace is expected to contain the project checkouts:

```
$HOAGS_WORKSPACE/
  eterna_automation/External/     git checkout, branch Eterna_automation
  lotier_automation/External/     git checkout, branch Lotier_automation
  build-secrets.env               GITUSER, GITTOKEN, AWS creds (chmod 600)
  renesas-devicefiles/            RL78 *.DVF (or set HOAGS_DEVICE_FILE)
```

Everything else — HE3 clones, build output, logs — is created on demand.

For anything that does not fit that layout, copy `config.ini.example` to
`config.ini` and set individual paths, or use the environment variable for
each. Precedence is **environment > config.ini > default**.

## Requirements

Required: `git`, `make`, `python3`.
Per toolchain: `ccrl`/`rlink` (RL78), `arm-none-eabi-gcc` (RA + HE3 SDK).
HE3 build also wants `jq` and `zip`. `aws` only for `--ci`.

`doctor` reports exactly which of these are missing and what needs them.

**The RL78 device file is not optional.** Without `DR5F121BC.DVF`, rlink
cannot resolve the RAM mirror region and the link fails — there is no
workaround. It is not in the compiler package; extract it from an e2 studio
installer:

```
install/repos/rl78-supportfiles/plugins/
  com.renesas.ide.supportfiles.rl78.devicefiles_*.jar
    → devicefiles_support.tar.xz → RL78/Common/DR5F121BC.DVF
```

Drop it in `$HOAGS_WORKSPACE/renesas-devicefiles/RL78/Common/` and it is
found automatically. The CC-RL install directory is discovered too, so its
version number is not baked in anywhere.

## Commands

| command | does |
|---|---|
| `hoags-build doctor` | check machine, print resolved config |
| `hoags-build list` | show paths without doing anything |
| `hoags-build firmware [P]` | pull + compile + convert |
| `hoags-build release [P]` | + stage into a local HE3 checkout (no push) |
| `hoags-build he3 [P]` | + push and build HE3 |

`P` is `eterna` and/or `lotier`; omit for both. Useful flags:
`--no-pull`, `--no-compile`, `--skip-firmware`, `--build-type dev|test|mp`,
`--ci` (use the shared `build.sh`, which also uploads to S3 and rewrites the
OTA manifest — off by default).

## Files

```
config.py             path resolution and tool discovery
doctor.py             preflight check
build_firmware.py     project config; compile + convert
compile_firmware.py   toolchain fixups (see below) and the actual builds
pull_repos.py         pull + build orchestration
he3_release.py        stage into HE3, push, trigger the HE3 build
motTohex.py           .mot  → renesas_firmware.h
reneses_img_gen.py    .srec → reneses.bin
hoags-build           entry point
../new_build_script/  isolated HE3 build (own README)
```

## Why compilation happens in a copy

The e2 studio projects were authored on Windows and need fixups before they
build on Linux: Windows paths in generated makefiles, `-MAKEUD` and `-dev`
options the standalone compiler rejects, case-sensitive `#include`s, and
missing `subdir.mk` fragments. These are applied to a copy under
`<repo>/build/compile/`, never to the git checkout — the RL78 projects track
their own `.obj`/`.d` files, so building in place would dirty the tree and
make the next `--ff-only` pull fail.

## Known issues in the source

Not fixed here, because they are firmware changes rather than build changes:

- **CC-RL is on the 60-day evaluation licence.** When it lapses, `-Osize`
  silently degrades to `-Olite` and code size changes. Not suitable for
  production builds as-is.
- **`hal_entry.c` calls `APP_PRINT` without including `common_utilis.h`.**
  It links only because `--gc-sections` discards the unreferenced function.
  GCC 14 made this a hard error; the build passes `-Wno-error=...` to keep
  the reference toolchain's behaviour rather than silently changing what is
  accepted.
- **The RA build path is baked into the firmware.** FreeRTOS `configASSERT`
  embeds `__FILE__`, so absolute paths end up in flash. Builds are
  reproducible because the work directory is derived deterministically, but
  relocating the workspace changes the image. `-ffile-prefix-map` would fix
  it, at the cost of differing from the reference build.
