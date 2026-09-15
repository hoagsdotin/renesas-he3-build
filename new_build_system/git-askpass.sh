#!/usr/bin/env bash
# Feeds git credentials from the environment.
#
# Set GIT_ASKPASS to this script and git will call it instead of prompting,
# so remote URLs stay clean (https://github.com/org/repo) and no token is
# ever written into .git/config.
#
#   HOAGS_GIT_USER    account name  (default: git, which GitHub ignores)
#   HOAGS_GIT_TOKEN   personal access token
#
# git passes the prompt text as $1, e.g.
#   Username for 'https://github.com':
#   Password for 'https://user@github.com':

case "$1" in
*[Uu]sername*) printf '%s\n' "${HOAGS_GIT_USER:-git}" ;;
*[Pp]assword*) printf '%s\n' "${HOAGS_GIT_TOKEN:-}" ;;
*)             printf '%s\n' "${HOAGS_GIT_TOKEN:-}" ;;
esac
