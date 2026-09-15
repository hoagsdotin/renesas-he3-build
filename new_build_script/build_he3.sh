#!/bin/bash
# build_he3.sh -- build HE3 and produce output images. Nothing else.
#
# Isolated entry point: everything it needs lives in this directory. It does
# not read or modify ~/build-scripts.
#
# Runs the same stages as the original build.sh up to and including
# copyBuild, then stops. The S3 upload, the OTA manifest rewrite for
# CI_TEST_MAC, and incrementVersionFile are deliberately NOT run -- this
# produces a build artifact, it does not drive the CI/OTA pipeline.
#
# Usage:
#   bash build_he3.sh --branch LOTIER_BUILD_AUTOMATION --type dev \
#        --flashsize 4MB --board he3 --customer LIVPURE_PURIFIER \
#        --model LVPR0010001PURPX
#
# Secrets (GITUSER, GITTOKEN, ...) come from $BUILD_SECRETS_FILE, default
# ~/build-secrets.env. GITHUBORG selects the repository owner and defaults
# to hoagstech.

set -o pipefail

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$_HERE" || exit 1

HOAGS_WORKSPACE="${HOAGS_WORKSPACE:-$HOME}"
SECRETS_FILE="${BUILD_SECRETS_FILE:-${HOAGS_SECRETS:-$HOAGS_WORKSPACE/build-secrets.env}}"
if [ -f "$SECRETS_FILE" ]; then
	# The secrets file provides defaults, but anything the caller explicitly
	# exported must win. Sourcing it unconditionally would overwrite an
	# override such as GITUSER/GITHUBORG with the file's own value and send
	# the build at the wrong repository -- with the wrong account's token.
	_pre_GITUSER="$GITUSER"
	_pre_GITTOKEN="$GITTOKEN"
	_pre_GITHUBORG="$GITHUBORG"
	_pre_GITHUBREPO="$GITHUBREPO"
	_pre_GITBRANCH="$GITBRANCH"
	_pre_CHECKOUTPATH="$CHECKOUTPATH"

	set -a
	source "$SECRETS_FILE"
	set +a

	[ -n "$_pre_GITUSER" ]      && GITUSER="$_pre_GITUSER"
	[ -n "$_pre_GITTOKEN" ]     && GITTOKEN="$_pre_GITTOKEN"
	[ -n "$_pre_GITHUBORG" ]    && GITHUBORG="$_pre_GITHUBORG"
	[ -n "$_pre_GITHUBREPO" ]   && GITHUBREPO="$_pre_GITHUBREPO"
	[ -n "$_pre_GITBRANCH" ]    && GITBRANCH="$_pre_GITBRANCH"
	[ -n "$_pre_CHECKOUTPATH" ] && CHECKOUTPATH="$_pre_CHECKOUTPATH"
	export GITUSER GITTOKEN GITHUBORG GITHUBREPO GITBRANCH CHECKOUTPATH
else
	echo "WARNING: $SECRETS_FILE not found -- GITUSER/GITTOKEN must already be exported." >&2
fi

source "$_HERE/vars_he3.sh"
source "$_HERE/funcs_he3.sh"

while :
do
	case "$1" in
	-f | --flashsize )      FLASH="$2"; shift 2 ;;
	-r | --branch )         GITBRANCH="$2"; shift 2 ;;
	-t | --type )           TYPE="$2"; shift 2 ;;
	-b | --board)           BOARD="$2"; shift 2 ;;
	-c | --customer)        CUSTOMER="$2"; shift 2 ;;
	-s | --sha )            SHA="$2"; shift 2 ;;
	-a | --capability )     CAPLEVEL="$2"; shift 2 ;;
	-l | --loglevel)        LOGLVL="$2"; shift 2 ;;
	-m | --securedImg )     SECUREDBUILD="$2"; shift 2 ;;
	-n | --securedSoc )     SECUREDSOC="$2"; shift 2 ;;
	-u | --uartLogDisable ) UARTLOGDISABLE="$2"; shift 2 ;;
	-i | --filterSetting )  FILTERSETTING="$2"; shift 2 ;;
	--model )               MODEL="$2"; shift 2 ;;
	--note )                NOTE="$2"; shift 2 ;;
	*) break ;;
	esac
done

# Defaults for anything not passed, so the script is usable without
# repeating every flag every time.
SECUREDBUILD="${SECUREDBUILD:-0}"
SECUREDSOC="${SECUREDSOC:-0}"
UARTLOGDISABLE="${UARTLOGDISABLE:-0}"
FILTERSETTING="${FILTERSETTING:-0}"
CAPLEVEL="${CAPLEVEL:-4}"
LOGLVL="${LOGLVL:-1}"
MODEL="${MODEL:-TEST001}"

export CUSTOMERNAME=$CUSTOMER
export LOGLEVEL=$LOGLVL
export CAPABILITY=$CAPLEVEL
export SECURESOC=$SECUREDSOC
export UART_LOG_DISABLE=$UARTLOGDISABLE
export FILTER_SETTING=$FILTERSETTING
export MODEL_NUMBER=$MODEL
export FLASH_SIZE="${FLASH%MB}"

echo "=========================================================="
echo "repo          $GITHUBORG/$GITHUBREPO"
echo "git user      $GITUSER"
echo "branch        $GITBRANCH"
echo "sha           $SHA"
echo "type          $TYPE"
echo "customer      $CUSTOMERNAME"
echo "board         $BOARD"
echo "flash         $FLASH_SIZE MB"
echo "model         $MODEL"
echo "securedImg    $SECUREDBUILD"
echo "checkoutpath  $CHECKOUTPATH"
echo "versions      $VERSIONDIR"
echo "output        $TARGETIMAGEPATH"
echo "=========================================================="

mkdir -p "$CHECKOUTPATH" "$TARGETIMAGEPATH" "$VERSIONDIR"

# Seed version counters on first use so a fresh clone of this build system
# works without hand-created files.
for _f in "$DEVVERSIONFILE" "$TESTVERSIONFILE" "$PRODVERSIONFILE"; do
	[ -f "$_f" ] || echo 1 > "$_f"
done

# genOTAHostingBuild runs these from inside CHECKOUTPATH, and
# HE3_renesas_image_gen.py locates the SDK relative to its own file, so they
# have to physically sit there. Stage them from this directory on every run
# so the copy in the checkout can never drift from the one under review.
for _h in "${HELPER_SCRIPTS[@]}"; do
	if [ -f "$_HERE/$_h" ]; then
		cp -f "$_HERE/$_h" "$CHECKOUTPATH/$_h"
	else
		echo "WARNING: helper script missing: $_HERE/$_h" >&2
	fi
done

printParams
checkParams
getCode
useTypeInfo
useBoardInfo
useCustomerInfo
generateSecuredKeys
versioning
build
genOTAHostingBuild "$MODEL"
copyBuild

echo ""
echo "=========================================================="
echo "BUILD_NAME=$BUILDNAME"
echo "BUILD_VERSION=$VERSION"
echo "BUILD_PATH=$TARGETIMAGEPATH/$BUILDNAME"
echo "GIT_SHA=$GITSHA"
echo "GIT_BRANCH=$GITBRANCH"

_BIN="$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/Debug/bin"
echo ""
echo "--- images ---"
_missing=0
for f in "$_BIN/firmware_is.bin" "$_BIN/flash_is.bin" \
         "$_BIN/Flash and OTA files/HE3_renesas_flash_is.bin" \
         "$_BIN/Flash and OTA files/HE3_renesas_firmware_is.bin" \
         "$_BIN/Flash and OTA files/OTA_final_he3_renesas.bin"; do
	if [ -f "$f" ]; then
		printf '  %10d  %s\n' "$(stat -c%s "$f")" "$(basename "$f")"
	else
		printf '  %10s  %s\n' "MISSING" "$(basename "$f")"
		_missing=$((_missing+1))
	fi
done
echo "=========================================================="
echo "NOTE: S3 upload / OTA manifest / version increment were skipped."

# The zip is the deliverable; if it is absent the build did not really work,
# regardless of what the individual stages reported.
if [ ! -f "$TARGETIMAGEPATH/$BUILDNAME" ]; then
	echo "ERROR: expected build archive not found: $TARGETIMAGEPATH/$BUILDNAME" >&2
	exit 1
fi
exit 0
