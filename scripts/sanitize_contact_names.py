#!/usr/bin/env python3
"""Remove line breaks from the stored contact names.

A contact name is written into the headers of the messages we send, so a name
holding a line break injects a header in them. Names are sanitized on creation
now, this cleans up the ones stored before that.

Runs read-only unless --apply is given:

    python scripts/sanitize_contact_names.py            # report only
    python scripts/sanitize_contact_names.py --apply
"""

import argparse

from sqlalchemy import func

from app.db import Session
from app.email_utils import sanitize_header_value
from app.log import LOG
from app.models import Contact

# postgres regex, a name is only a problem if it holds a CR or a LF
AFFECTED_NAME_REGEX = "[\r\n]"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the sanitized names. Without it nothing is modified",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="how many ids to look at per query",
    )
    args = parser.parse_args()

    max_contact_id = Session.query(func.max(Contact.id)).scalar() or 0
    LOG.i(f"Walking the contacts up to id {max_contact_id}")

    # walk fixed id windows rather than asking for the next matching rows. The
    # regex cannot use an index, so every query has to scan what it covers:
    # bounding the window bounds the work each of them does, no matter how far
    # apart the affected contacts are
    last_batch_id = 0
    found = 0
    while last_batch_id < max_contact_id:
        contacts = Contact.filter(
            Contact.id > last_batch_id,
            Contact.id <= last_batch_id + args.batch_size,
            Contact.name.op("~")(AFFECTED_NAME_REGEX),
        ).all()

        if contacts:
            found += len(contacts)
            for contact in contacts:
                sanitized = sanitize_header_value(contact.name)
                LOG.i(
                    f"Contact {contact.id} (user {contact.user_id}, alias {contact.alias_id}): "
                    f"{contact.name!r} -> {sanitized!r}"
                )
                if args.apply:
                    contact.name = sanitized
            if args.apply:
                Session.commit()
            # do not keep every contact we looked at in the identity map
            Session.expunge_all()
            LOG.i(
                f"Walked ids up to {last_batch_id + args.batch_size}, "
                f"{found} affected so far"
            )

        last_batch_id += args.batch_size

    if args.apply:
        LOG.i(f"Sanitized {found} contact names")
    else:
        LOG.i(
            f"Dry run, {found} contact names would be sanitized. "
            "Pass --apply to write the changes"
        )


if __name__ == "__main__":
    main()
