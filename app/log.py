import logging
import sys
import time

import coloredlogs

from app.config import (
    COLOR_LOG,
)

# this format allows clickable link to code source in PyCharm
_log_format = '%(asctime)s - %(name)s - %(levelname)s - "%(pathname)s:%(lineno)d" - %(funcName)s() - %(message)s'
_log_formatter = logging.Formatter(_log_format)


def _get_console_handler():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(_log_formatter)
    console_handler.formatter.converter = time.gmtime

    return console_handler


def _get_logger(name):
    logger = logging.getLogger(name)

    logger.setLevel(logging.DEBUG)

    # leave the handlers level at NOTSET so the level checking is only handled by the logger
    logger.addHandler(_get_console_handler())

    # no propagation to avoid propagating to root logger
    logger.propagate = False

    if COLOR_LOG:
        coloredlogs.install(level="DEBUG", logger=logger, fmt=_log_format)

    return logger


print(">>> init logging <<<")

# Disable flask logs such as 127.0.0.1 - - [15/Feb/2013 10:52:22] "GET /index.html HTTP/1.1" 200
log = logging.getLogger("werkzeug")
log.disabled = True

# Set some shortcuts
logging.Logger.d = logging.Logger.debug
logging.Logger.i = logging.Logger.info

LOG = _get_logger("SL")
