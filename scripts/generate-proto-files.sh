#!/bin/bash

set -euxo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" || exit 1; pwd -P)"
REPO_ROOT=$(echo "${SCRIPT_DIR}" | sed 's:scripts::g')

DEST_DIR="${REPO_ROOT}/app/events/generated"

PROTOC=${PROTOC:-"protoc"}

if ! eval "${PROTOC} --version" &> /dev/null ; then
  echo "Cannot find $PROTOC"
  exit 1
fi

rm -rf "${DEST_DIR}"
mkdir -p "${DEST_DIR}"

pushd $REPO_ROOT || exit 1

eval "${PROTOC} --proto_path=proto --python_out=\"${DEST_DIR}\" --pyi_out=\"${DEST_DIR}\" proto/event.proto"

popd || exit 1
