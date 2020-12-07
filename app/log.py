import logging
import sys
import time

import boto3
import coloredlogs
import watchtower

from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_REGION,
    CLOUDWATCH_LOG_GROUP,
    ENABLE_CLOUDWATCH,
    CLOUDWATCH_LOG_STREAM,
    COLOR_LOG,
)

_log_format = "%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(module)s:%(lineno)d - %(funcName)s - %(message)s"
_log_formatter = logging.Formatter(_log_format)


def _get_console_handler():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(_log_formatter)
    console_handler.formatter.converter = time.gmtime

    return console_handler


def _get_watchtower_handler():
    session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )

    handler = watchtower.CloudWatchLogHandler(
        log_group=CLOUDWATCH_LOG_GROUP,
        stream_name=CLOUDWATCH_LOG_STREAM,
        send_interval=5,  # every 5 sec
        boto3_session=session,
    )

    handler.setFormatter(_log_formatter)

    return handler


def _get_logger(name):
    logger = logging.getLogger(name)

    logger.setLevel(logging.DEBUG)

    # leave the handlers level at NOTSET so the level checking is only handled by the logger
    logger.addHandler(_get_console_handler())

    if ENABLE_CLOUDWATCH:
        print(
            "enable cloudwatch, log group",
            CLOUDWATCH_LOG_GROUP,
            "; log stream:",
            CLOUDWATCH_LOG_STREAM,
        )
        logger.addHandler(_get_watchtower_handler())

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

LOG = _get_logger("sl")
