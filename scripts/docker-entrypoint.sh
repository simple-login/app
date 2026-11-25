#!/bin/sh
# Runs the container command as root by default. If SL_UID is set, drop to that
# UID (and SL_GID, defaulting to SL_UID) before executing anything.
set -e

if [ -n "${SL_UID}" ]; then
    SL_GID="${SL_GID:-${SL_UID}}"
    case "${SL_UID}${SL_GID}" in
        *[!0-9]*)
            echo "SL_UID and SL_GID must be numeric (got SL_UID=${SL_UID} SL_GID=${SL_GID})" >&2
            exit 1
            ;;
    esac
    if [ "$(id -u)" != "${SL_UID}" ]; then
        export HOME=/tmp
        exec setpriv --reuid="${SL_UID}" --regid="${SL_GID}" --clear-groups -- "$@"
    fi
fi

exec "$@"
