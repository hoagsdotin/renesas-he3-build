# new_build_script — isolated HE3 build

Self-contained HE3 build. Reads nothing from, and writes nothing to,
`~/build-scripts`.

```
vars_he3.sh                configuration
funcs_he3.sh               build stages (getCode / build / versioning / ...)
build_he3.sh               entry point
HE3_renesas_image_gen.py   combines firmware_is.bin + reneses.bin
versions/                  dev/test/prod build counters
```

## Run

```bash
bash build_he3.sh --branch LOTIER_BUILD_AUTOMATION --type dev \
     --flashsize 4MB --board he3 --customer LIVPURE_PURIFIER \
     --model LVPR0010001PURPX
```

Usually driven from `../new_build_system/he3_release.py`, which builds the
Renesas firmware, publishes it into the HE3 repo and then calls this.

Secrets come from `$BUILD_SECRETS_FILE` (default `~/build-secrets.env`):
`GITUSER`, `GITTOKEN`. `GITHUBORG` selects the repository owner, default
`hoagstech`.

## What it does not do

Stops after `copyBuild`. No S3 upload, no OTA manifest rewrite for
`CI_TEST_MAC`, no version-counter increment. Use `he3_release.py --ci` to run
the shared `the shared build.sh` if you want the full CI pipeline.

## Paths

| what | default | override |
|---|---|---|
| HE3 clone | `$HOAGS_WORKSPACE/he3-build/HE3` | `CHECKOUTPATH` |
| version counters | `./versions/` | `VERSIONDIR` |
| output zip | `~/http-server/local/he3/` | `TARGETIMAGEPATH` |

`CHECKOUTPATH` is `git reset --hard` + `git clean -fd` on every run. Never
point it at a tree anyone edits by hand.

## Differences from the shared build-scripts

Bugs fixed here (the shared copies are noted in the handover, not silently
changed):

- **`isError` exited 0 on failure.** A bare `exit` returns the status of the
  preceding `echo`, so every failure it caught was reported as success.
- **`getCode` checked out before resetting.** The build modifies tracked
  files, so switching branches aborted with "local changes would be
  overwritten". Only bit when consecutive builds used different branches —
  and bug 1 hid it.
- **`updateToken` only echoed** `git remote set-url`, so an existing checkout
  kept whatever remote it was cloned from.
- **`genOTAHostingBuild` printed "success" unconditionally**, including when
  the script it ran was absent. Now reports SKIP and checks the exit status.

Improvements:

- `GITHUBORG` is separate from `GITUSER`; the original could only ever build
  `github.com/$GITUSER/HE3`.
- Version counters live with the build system, not in the checkout, so
  pointing at a different checkout no longer resets the numbering.
- `build_he3.sh` fails if the expected archive is missing, rather than
  trusting the individual stages.
