#!/usr/bin/env python3
import argparse


from app.log import LOG
from app.models import Alias, SLDomain
from app.db import Session

parser = argparse.ArgumentParser(
    prog="Mark partner created aliases with the PARTNER_CREATED flag",
)
args = parser.parse_args()

domains = SLDomain.filter(SLDomain.partner_id.isnot(None)).all()

for domain in domains:
    LOG.i(f"Checking aliases for domain {domain.domain}")
    for alias in (
        Alias.filter(
            Alias.email.like(f"%{domain.domain}"),
            Alias.flags.op("&")(Alias.FLAG_PARTNER_CREATED) == 0,
        )
        .enable_eagerloads(False)
        .yield_per(100)
        .all()
    ):
        alias.flags = alias.flags | Alias.FLAG_PARTNER_CREATED
        LOG.i(f" * Updating {alias.email} to {alias.flags}")
        Session.commit()
