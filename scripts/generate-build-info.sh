#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" || exit 1; pwd -P)"
REPO_ROOT=$(echo "${SCRIPT_DIR}" | sed 's:scripts::g')
BUILD_INFO_FILE="${REPO_ROOT}/app/build_info.py"

if [[ -z "$2" ]]; then
  echo "Invalid usage. Usage: $0 SHA VERSION"
  exit 1
fi

SHA="$1"
echo "SHA1 = \"${SHA}\"" > $BUILD_INFO_FILE
BUILD_TIME=$(date +%s)
echo "BUILD_TIME = \"${BUILD_TIME}\"" >> $BUILD_INFO_FILE
VERSION="$2"
echo "VERSION = \"${VERSION}\"" >> $BUILD_INFO_FILE
