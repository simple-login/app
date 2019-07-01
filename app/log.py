import logging
import sys
import time

_log_format = "%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(module)s:%(lineno)d - %(funcName)s - %(message)s"
_log_formatter = logging.Formatter(_log_format)


def _get_console_handler(level=None):
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(_log_formatter)
    console_handler.formatter.converter = time.gmtime

    if level:
        console_handler.setLevel(level)

    return console_handler


def get_logger(name):
    logger = logging.getLogger(name)

    logger.setLevel(logging.DEBUG)

    # leave the handlers level at NOTSET so the level checking is only handled by the logger
    logger.addHandler(_get_console_handler())

    # no propagation to avoid unexpected behaviour
    logger.propagate = False

    return logger


print(f">>> init logging <<<")

# ### config root logger ###
# do not use the default (buggy) logger
logging.root.handlers.clear()

# add handlers with the default level = "warn"
# need to add level at handler level as there's no level check in root logger
# all the libs logs having level >= WARN will be handled by these 2 handlers
logging.root.addHandler(_get_console_handler(logging.WARN))

LOG = get_logger("yourkey")
