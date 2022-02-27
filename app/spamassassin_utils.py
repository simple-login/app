"""Inspired from
https://github.com/petermat/spamassassin_client
"""
import logging
import socket
from io import BytesIO

import re2 as re
import select

from app.log import LOG

divider_pattern = re.compile(rb"^(.*?)\r?\n(.*?)\r?\n\r?\n", re.DOTALL)
first_line_pattern = re.compile(rb"^SPAMD/[^ ]+ 0 EX_OK$")


class SpamAssassin(object):
    def __init__(self, message, timeout=20, host="127.0.0.1", spamd_user="spamd"):
        self.score = None
        self.symbols = None
        self.spamd_user = spamd_user
        self.report_json = dict()
        self.report_fulltext = ""
        self.score = -999

        # Connecting
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect((host, 783))

        # Sending
        client.sendall(self._build_message(message))
        client.shutdown(socket.SHUT_WR)

        # Reading
        resfp = BytesIO()
        while True:
            ready = select.select([client], [], [], timeout)
            if ready[0] is None:
                # Kill with Timeout!
                logging.info("[SpamAssassin] - Timeout ({0}s)!".format(str(timeout)))
                break

            data = client.recv(4096)
            if data == b"":
                break

            resfp.write(data)

        # Closing
        client.close()
        client = None

        self._parse_response(resfp.getvalue())

    def _build_message(self, message):
        reqfp = BytesIO()
        data_len = str(len(message)).encode()
        reqfp.write(b"REPORT SPAMC/1.2\r\n")
        reqfp.write(b"Content-Length: " + data_len + b"\r\n")
        reqfp.write(f"User: {self.spamd_user}\r\n\r\n".encode())
        reqfp.write(message)
        return reqfp.getvalue()

    def _parse_response(self, response):
        if response == b"":
            logging.info("[SPAM ASSASSIN] Empty response")
            return None

        match = divider_pattern.match(response)
        if not match:
            logging.error("[SPAM ASSASSIN] Response error:")
            logging.error(response)
            return None

        first_line = match.group(1)
        headers = match.group(2)
        body = response[match.end(0) :]

        # Checking response is good
        match = first_line_pattern.match(first_line)
        if not match:
            logging.error("[SPAM ASSASSIN] invalid response:")
            logging.error(first_line)
            return None

        report_list = [
            s.strip() for s in body.decode("utf-8", errors="ignore").strip().split("\n")
        ]
        linebreak_num = report_list.index([s for s in report_list if "---" in s][0])
        tablelists = [s for s in report_list[linebreak_num + 1 :]]

        self.report_fulltext = "\n".join(report_list)

        # join line when current one is only wrap of previous
        tablelists_temp = []
        if tablelists:
            for _, tablelist in enumerate(tablelists):
                if len(tablelist) > 1:
                    if (tablelist[0].isnumeric() or tablelist[0] == "-") and (
                        tablelist[1].isnumeric() or tablelist[1] == "."
                    ):
                        tablelists_temp.append(tablelist)
                    else:
                        if tablelists_temp:
                            tablelists_temp[-1] += " " + tablelist
        tablelists = tablelists_temp

        # create final json
        self.report_json = dict()
        for tablelist in tablelists:
            wordlist = re.split(r"\s+", tablelist)
            try:
                self.report_json[wordlist[1]] = {
                    "partscore": float(wordlist[0]),
                    "description": " ".join(wordlist[1:]),
                }
            except ValueError:
                LOG.w("Cannot parse %s %s", wordlist[0], wordlist)

        headers = (
            headers.decode("utf-8")
            .replace(" ", "")
            .replace(":", ";")
            .replace("/", ";")
            .split(";")
        )
        self.score = float(headers[2])

    def get_report_json(self):
        return self.report_json

    def get_score(self):
        return self.score

    def is_spam(self, level=5):
        return self.score is None or self.score > level

    def get_fulltext(self):
        return self.report_fulltext
