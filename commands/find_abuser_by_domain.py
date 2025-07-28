import argparse
import sys
import time

from sqlalchemy import func

from app.abuser_audit_log_utils import emit_abuser_audit_log, AbuserAuditLogAction
from app.db import Session
from app.jobs.mark_abuser_job import MarkAbuserJob
from app.log import LOG
from app.models import User

parser = argparse.ArgumentParser(
    prog="Disable abusers by mailbox domain",
    description="Find abusers that created an account with domain and optionally disable them",
)
parser.add_argument(
    "-s", "--start_user_id", default=0, type=int, help="Initial user_id"
)
parser.add_argument("-e", "--end_user_id", default=0, type=int, help="Last user_id")
parser.add_argument(
    "-d",
    "--domain",
    required=True,
    type=str,
    help="Domain used to create the mailboxes",
)
parser.add_argument(
    "-x",
    "--disable",
    default=False,
    help="Whether to disable the users and mark as abusers",
    action="store_true",
)

args = parser.parse_args()
domain = args.domain
if not domain:
    LOG.i("No domain specified")
    sys.exit(1)
disable = args.disable
user_id_start = args.start_user_id
max_user_id = args.end_user_id
if max_user_id == 0:
    max_user_id = Session.query(func.max(User.id)).scalar()

LOG.i(f"Checking user {user_id_start} to {max_user_id}")
step = 1000
sql = """
    SELECT u.id, u.email, min(m.email)
    FROM users u
    LEFT JOIN mailbox m ON u.id = m.user_id
    WHERE u.id>=:start AND u.id < :end AND u.disabled = False AND (m.email LIKE '%' || :domain OR u.email LIKE '%' || :domain)
    GROUP BY u.id, u.email
    """
updated = 0
start_time = time.time()
if disable:
    LOG.i("Users will be marked as abusers and disabled!")
else:
    LOG.i("Users will NOT be marked as abusers")
for batch_start in range(user_id_start, max_user_id, step):
    rows = Session.execute(
        sql,
        {
            "start": batch_start,
            "end": batch_start + step,
            "domain": domain,
        },
    )
    for row in rows:
        LOG.i(f"Found UserID: {row[0]} : {row[1]} / {row[2]}")
        if disable:
            abuse_user = User.get(row[0])
            abuse_user.disabled = True

            emit_abuser_audit_log(
                user_id=abuse_user.id,
                action=AbuserAuditLogAction.MarkAbuser,
                message="Filled through find_abuser_by_domain script",
                admin_id=None,
            )
            job = MarkAbuserJob(user=abuse_user).store_job_in_db()
            LOG.i(f"Marked user {abuse_user} as abuser with job {job}")
            Session.commit()

    elapsed = time.time() - start_time
    time_per_alias = elapsed / (updated + 1)
    last_batch_id = batch_start + step
    remaining = max_user_id - last_batch_id
    time_remaining = (max_user_id - last_batch_id) * time_per_alias
    hours_remaining = time_remaining / 3600.0
    LOG.i(
        f"User {batch_start}/{max_user_id} {updated} {hours_remaining:.2f}hrs remaining"
    )
