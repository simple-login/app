import logging
import sys
import time

import coloredlogs

from app.config import (
    COLOR_LOG,
)

# this format allows clickable link to code source in PyCharm
_log_format = (
    "%(asctime)s - %(name)s - %(levelname)s - %(process)d - "
    '"%(pathname)s:%(lineno)d" - %(funcName)s() - %(message_id)s - %(message)s'
)
_log_formatter = logging.Formatter(_log_format)

# used to keep track of an email lifecycle
_MESSAGE_ID = ""


def set_message_id(message_id):
    global _MESSAGE_ID
    LOG.d("set message_id %s", message_id)
    _MESSAGE_ID = message_id


class EmailHandlerFilter(logging.Filter):
    """automatically add message-id to keep track of an email processing"""

    def filter(self, record):
        message_id = self.get_message_id()
        record.message_id = message_id if message_id else ""
        return True

    def get_message_id(self):
        return _MESSAGE_ID


def _get_console_handler():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(_log_formatter)
    console_handler.formatter.converter = time.gmtime

    return console_handler


def _get_logger(name) -> logging.Logger:
    logger = logging.getLogger(name)

    logger.setLevel(logging.DEBUG)

    # leave the handlers level at NOTSET so the level checking is only handled by the logger
    logger.addHandler(_get_console_handler())

    logger.addFilter(EmailHandlerFilter())

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
logging.Logger.w = logging.Logger.warning
logging.Logger.e = logging.Logger.exception

LOG = _get_logger("SL")
