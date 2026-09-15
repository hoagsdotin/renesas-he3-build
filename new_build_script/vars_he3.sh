#!/bin/bash
# vars_he3.sh -- configuration for the isolated HE3 build.
#
# Self-contained copy, derived from build-scripts/varsHE3.sh. Differences
# from the original, all deliberate:
#
#   * GITHUBORG is separate from GITUSER, so the token's account and the
#     repository owner do not have to be the same. The original hardcoded
#     github.com/$GITUSER/HE3, which meant a token belonging to one account
#     could only ever build that account's fork.
#   * CHECKOUTPATH defaults to a directory owned by this system, so a build
#     never resets or cleans somebody else's working tree.
#   * The version counters live next to these scripts, not in the checkout,
#     because they are state of the build system rather than of the source.
#   * Paths are derived from this file's location instead of $HOME.

_VARS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Base directory for everything not explicitly overridden. Matches
# HOAGS_WORKSPACE in the Python side (config.py); defaults to $HOME, which is
# the usual layout. Set it to relocate the whole system.
HOAGS_WORKSPACE="${HOAGS_WORKSPACE:-$HOME}"

#fixed values
FLASH="NA"
TYPE="NA"
BOARD="NA"
CUSTOMER="NA"
CAPLEVEL=0
LOGLVL=1
SECURITYLIST=("0" "1")
LOGLEVELLIST=("1" "2" "3" "4" "5")
CAPABILITYLIST=("1" "2" "3" "4" "5" "47104" "47360")
FLASHLIST=("2MB" "8MB" "4MB" "256KB")
BOARDLIST=("htap" "evb" "htap-mini" "he2-rev1" "he3")

CUSTOMERLIST=("AMBER_AC" "AMBER_AIRCOOLER" "HAVELLS_FAN" "HAVELLS_HANDTUNED" "HAVELLS_AC" "BAJAJFAN" "VIRTUALFOREST_AC" "VERSADEVICES_SUPERFAN" "VERSADEVICES_SUPERFAN_IOT" "POLYCAB_FAN" "HOAGS_DEMO_LIGHT" "HOAGS_DEMO_FAN" "LIVPURE_CHIMNEY" "LIVPURE_CHIMNEY_SMOKE" "UNISEMI" "RR_KABLES" "ATOMBERG_FAN" "VGUARD_NEW_FAN" "OMNI_AC" "INDCOOL_AC" "LIVPURE_PURIFIER" "CRUISE_AC" "DIY" "HELIUM_AC" "NEOTERRA_AC" "INDCOOL_MEGMEET" "MOBILISE_FMHUB" "SYMPHONY_AIRCOOLER" "ORIENT" "BLDC_CHINESE")

# Where the HE3 clone lives. Owned by this build system -- getCode() resets
# and cleans it on every run, so it must not be a tree anyone edits by hand.
CHECKOUTPATH="${CHECKOUTPATH:-$HOAGS_WORKSPACE/he3-build}"
CHECKOUTPARENTFOLDER="HE3"
SHA="${SHA:-HEAD}"

#github specific
# Credentials come from the environment (build-secrets.env), never from the
# URL. getCode() runs `git remote set-url origin $GITHUBURL`, so a token in
# GITHUBURL would be written into the checkout's .git/config in plaintext.
HOAGS_GIT_TOKEN="${HOAGS_GIT_TOKEN:-$GITTOKEN}"
HOAGS_GIT_USER="${HOAGS_GIT_USER:-${GITUSER:-git}}"
: "${HOAGS_GIT_TOKEN:?No git token. Set HOAGS_GIT_TOKEN in build-secrets.env.}"

GITUSER="${GITUSER:-$HOAGS_GIT_USER}"
GITHUBORG="${GITHUBORG:-hoagstech}"
GITHUBREPO="${GITHUBREPO:-HE3}"
GITHUBURL="https://github.com/$GITHUBORG/$GITHUBREPO"

# Feed the token to git without putting it on disk or in the process list.
if [ -x "$_VARS_DIR/git-askpass.sh" ]; then
	export GIT_ASKPASS="$_VARS_DIR/git-askpass.sh"
	export HOAGS_GIT_TOKEN HOAGS_GIT_USER
fi
export GIT_TERMINAL_PROMPT=0
GITBRANCH="${GITBRANCH:-main}"
GITSHA="NA"

#patch folder
PATCHPATH="$_VARS_DIR/patches/"

#flash specific
FLASHCFGPATH="Entry/HE1/RTL872xEA_v10.1c_beta/component/soc/amebalite/fwlib/usrcfg/"
FLASHLDPATH="Entry/HE1/RTL872xEA_v10.1c_beta/project/realtek_amebaLite_va0_example/GCC-RELEASE/"
FLASHLDFILENAME="amebalite_layout.ld"
FLASHLDFILENAME2="amebalite_layout_2mb.ld"
FLASHLDFILENAME4="amebalite_layout_4mb.ld"
FLASHFILENAME="ameba_flashcfg.c"
FLASHFILENAME2="ameba_flashcfg_2mb.c"
FLASHFILENAME4="ameba_flashcfg_4mb.c"
FLASHCFG=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$FLASHCFGPATH/$FLASHFILENAME
FLASHCFG2=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$FLASHCFGPATH/$FLASHFILENAME2
FLASHCFG4=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$FLASHCFGPATH/$FLASHFILENAME4
FLASHLD=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$FLASHLDPATH/$FLASHLDFILENAME
FLASHLD2=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$FLASHLDPATH/$FLASHLDFILENAME2
FLASHLD4=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$FLASHLDPATH/$FLASHLDFILENAME4

#versioning
MAKEFILE="sdk-ameba-v7.1d/project/realtek_amebaz2_v0_example/GCC-RELEASE/application.is.mk"
MANIFESTFILE="sdk-ameba-v7.1d/project/realtek_amebaz2_v0_example/GCC-RELEASE/amebaz2_firmware_is.json"
MANIFESTFILE_BOOTLOADER="sdk-ameba-v7.1d/project/realtek_amebaz2_v0_example/GCC-RELEASE/amebaz2_bootloader.json"
MANIFESTFILEPATH=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$MANIFESTFILE
MANIFESTFILEPATH_BOOTLOADER=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$MANIFESTFILE_BOOTLOADER
MAKEFILE_PATH=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$MAKEFILE
VERSION_HEADER_FILE="$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/sdk-ameba-v7.1d/project/realtek_amebaz2_v0_example/inc/version.h"
MAJORDEV="0"
MAJORTEST="1"
MAJORPROD="2"

#security
SECURITYHAVELLSFOLDER="havells"
SECURITYVIRTUALFORESTFOLDER="virtualforest"
SECURITYVERSADEVICESFOLDER="versadevices"
SECURITYPOLYCABFOLDER="polycab"
SECURITYAMBERFOLDER="amber"
SECURITYLIVPUREFOLDER="livpure"
SECURITYPOCFOLDER="poc"
SECUREDPATH="./Entry/HE1/RTL872xEA_v10.1c_beta/project/realtek_amebaLite_va0_example/GCC-RELEASE/project_km4/asdk/gnu_utility/image_tool/securityKeys/"

#build
PLATFORM="he3"

# Version counters belong to the build system, so they sit beside these
# scripts. In the original they lived in CHECKOUTPATH, which meant pointing a
# build at a different checkout silently reset the numbering.
VERSIONDIR="${VERSIONDIR:-$_VARS_DIR/versions}"
DEVVERSIONFILE="$VERSIONDIR/devVersionHE3"
PRODVERSIONFILE="$VERSIONDIR/prodVersionHE3"
TESTVERSIONFILE="$VERSIONDIR/testVersionHE3"

VERSION="NA"
MAKEPATH="sdk-ameba-v7.1d/project/realtek_amebaz2_v0_example/GCC-RELEASE"
SRCIMAGEPATH="sdk-ameba-v7.1d/project/realtek_amebaz2_v0_example/GCC-RELEASE/application_is"

TARGETIMAGEPATH="${TARGETIMAGEPATH:-$HOAGS_WORKSPACE/http-server/local/he3/}"
BUILDLINK="${BUILDLINK:-http://$(hostname -I 2>/dev/null | awk '{print $1}')/builds/local/he3/}"

BUILDNAME=NA
BODYFILE="$_VARS_DIR/mailBody"
SUBJFILE="$_VARS_DIR/mailSubject"
NOTE=""

# Helper scripts that genOTAHostingBuild runs from inside CHECKOUTPATH.
# build_he3.sh stages these into the checkout directory before the build.
HELPER_SCRIPTS=("HE3_renesas_image_gen.py")
