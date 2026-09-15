#!/usr/bin/env bash
# setup.sh -- first-run bootstrap. Safe to re-run.
#
# Creates the workspace directories and a credentials template, then runs the
# health check. Touches nothing outside $HOAGS_WORKSPACE, installs nothing,
# and never overwrites an existing build-secrets.env.

set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
WS="${HOAGS_WORKSPACE:-$HOME}"

echo "workspace: $WS"
echo

mkdir -p "$WS/renesas-devicefiles/RL78/Common" \
         "$WS/build-logs" \
         "$WS/http-server/local/he3"
echo "created workspace directories"

SECRETS="${HOAGS_SECRETS:-$WS/build-secrets.env}"
if [ -f "$SECRETS" ]; then
	echo "kept existing $SECRETS"
else
	cat > "$SECRETS" <<'EOF'
# Credentials. Keep this file out of version control (chmod 600).
#
# Personal access token with repo scope. Use your own -- do not share one.
# Read only from here; never written into a git remote URL.
HOAGS_GIT_TOKEN=
HOAGS_GIT_USER=

# Only needed for --ci, which uploads to S3 and rewrites the OTA manifest.
#AWS_ACCESS_KEY_ID=
#AWS_SECRET_ACCESS_KEY=
#AWS_DEFAULT_REGION=ap-south-1
#CI_TEST_MAC=
EOF
	chmod 600 "$SECRETS"
	echo "wrote credentials template: $SECRETS"
	echo "  -> add your token before building"
fi

mkdir -p "$HERE/new_build_script/versions"

echo
echo "running health check..."
echo
exec "$HERE/new_build_system/hoags-build" doctor
