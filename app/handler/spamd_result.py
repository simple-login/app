from __future__ import annotations
from typing import Dict, Optional

import newrelic.agent

from app.email import headers
from app.log import LOG
from app.models import EnumE, Phase
from email.message import Message


class DmarcCheckResult(EnumE):
    allow = 0
    soft_fail = 1
    quarantine = 2
    reject = 3
    not_available = 4
    bad_policy = 5

    @staticmethod
    def get_string_dict():
        return {
            "DMARC_POLICY_ALLOW": DmarcCheckResult.allow,
            "DMARC_POLICY_SOFTFAIL": DmarcCheckResult.soft_fail,
            "DMARC_POLICY_QUARANTINE": DmarcCheckResult.quarantine,
            "DMARC_POLICY_REJECT": DmarcCheckResult.reject,
            "DMARC_NA": DmarcCheckResult.not_available,
            "DMARC_BAD_POLICY": DmarcCheckResult.bad_policy,
        }


class SPFCheckResult(EnumE):
    allow = 0
    fail = 1
    soft_fail = 1
    neutral = 2
    temp_error = 3
    not_available = 4
    perm_error = 5

    @staticmethod
    def get_string_dict():
        return {
            "R_SPF_ALLOW": SPFCheckResult.allow,
            "R_SPF_FAIL": SPFCheckResult.fail,
            "R_SPF_SOFTFAIL": SPFCheckResult.soft_fail,
            "R_SPF_NEUTRAL": SPFCheckResult.neutral,
            "R_SPF_DNSFAIL": SPFCheckResult.temp_error,
            "R_SPF_NA": SPFCheckResult.not_available,
            "R_SPF_PERMFAIL": SPFCheckResult.perm_error,
        }


class SpamdResult:
    def __init__(self, phase: Phase = Phase.unknown):
        self.phase: Phase = phase
        self.dmarc: DmarcCheckResult = DmarcCheckResult.not_available
        self.spf: SPFCheckResult = SPFCheckResult.not_available
        self.rspamd_score = -1

    def set_dmarc_result(self, dmarc_result: DmarcCheckResult):
        self.dmarc = dmarc_result

    def set_spf_result(self, spf_result: SPFCheckResult):
        self.spf = spf_result

    def event_data(self) -> Dict:
        return {
            "header": "present",
            "dmarc": self.dmarc.name,
            "spf": self.spf.name,
            "phase": self.phase.name,
        }

    @classmethod
    def extract_from_headers(
        cls, msg: Message, phase: Phase = Phase.unknown
    ) -> Optional[SpamdResult]:
        cached = cls._get_from_message(msg)
        if cached:
            return cached

        spam_result_header = msg.get_all(headers.SPAMD_RESULT)
        if not spam_result_header:
            return None

        spam_entries = [
            entry.strip() for entry in str(spam_result_header[-1]).split("\n")
        ]

        for entry_pos in range(len(spam_entries)):
            sep = spam_entries[entry_pos].find("(")
            if sep > -1:
                spam_entries[entry_pos] = spam_entries[entry_pos][:sep]

        spamd_result = SpamdResult(phase)

        for header_value, dmarc_result in DmarcCheckResult.get_string_dict().items():
            if header_value in spam_entries:
                spamd_result.set_dmarc_result(dmarc_result)
                break
        for header_value, spf_result in SPFCheckResult.get_string_dict().items():
            if header_value in spam_entries:
                spamd_result.set_spf_result(spf_result)
                break

        # parse the rspamd score
        try:
            score_line = spam_entries[0]  # e.g. "default: False [2.30 / 13.00];"
            spamd_result.rspamd_score = float(
                score_line[(score_line.find("[") + 1) : score_line.find("]")]
                .split("/")[0]
                .strip()
            )
        except (IndexError, ValueError):
            LOG.e("cannot parse rspamd score")

        cls._store_in_message(spamd_result, msg)
        return spamd_result

    @classmethod
    def _store_in_message(cls, check: SpamdResult, msg: Message):
        msg.spamd_check = check

    @classmethod
    def _get_from_message(cls, msg: Message) -> Optional[SpamdResult]:
        return getattr(msg, "spamd_check", None)

    @classmethod
    def send_to_new_relic(cls, msg: Message):
        check = cls._get_from_message(msg)
        if check:
            newrelic.agent.record_custom_event("SpamdCheck", check.event_data())
        else:
            newrelic.agent.record_custom_event("SpamdCheck", {"header": "missing"})
