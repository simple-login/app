#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" || exit 1; pwd -P)"
REPO_ROOT=$(echo "${SCRIPT_DIR}" | sed 's:scripts::g')
BUILD_INFO_FILE="${REPO_ROOT}/app/build_info.py"

if [[ -z "$1" ]]; then
  echo "This script needs to be invoked with the version as an argument"
  exit 1
fi

VERSION="$1"
echo "SHA1 = \"${VERSION}\"" > $BUILD_INFO_FILE
BUILD_TIME=$(date +%s)
echo "BUILD_TIME = \"${BUILD_TIME}\"" >> $BUILD_INFO_FILE
