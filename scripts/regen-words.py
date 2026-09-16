#!/usr/bin/env python3
import os
import sys
import json

rootDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(rootDir)

from app import config  # noqa: E402
from app.log import LOG  # noqa: E402

LOG.i(f"Reading {config.WORDS_FILE_PATH} file")
words = sorted(
    [
        word.strip()
        for word in open(config.WORDS_FILE_PATH, "r").readlines()
        if word.strip()
    ]
)

destFile = os.path.join(rootDir, "app", "words.py")
LOG.i(f"Writing {destFile}")

serialized_words = json.dumps(words, indent=2)
with open(destFile, "wb") as fd:
    fd.write(
        f"""#
# This file is auto-generated. Please run {sys.argv[0]} to re-generate it
#

import json

safe_words = json.loads(
    \"\"\"{serialized_words}\"\"\"
)
""".encode("utf-8")
    )
