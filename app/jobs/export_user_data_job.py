from __future__ import annotations

import json
import zipfile
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from typing import List, Dict, Optional

import arrow
import sqlalchemy

from app import config
from app.db import Session
from app.email import headers
from app.email_utils import generate_verp_email, render, add_dkim_signature
from app.mail_sender import sl_sendmail
from app.models import (
    Alias,
    Contact,
    Mailbox,
    Directory,
    EmailLog,
    CustomDomain,
    RefusedEmail,
    Base,
    User,
    EnumE,
    TransactionalEmail,
    VerpType,
    Job,
)


class ExportUserDataJob:

    REMOVE_FIELDS = {
        "User": ("otp_secret",),
        "Alias": ("ts_vector", "transfer_token", "hibp_last_check"),
        "CustomDomain": ("ownership_txt_token",),
    }

    def __init__(self, user: User):
        self._user: User = user

    def _get_paginated_model(self, model_class, page_size=50) -> List:
        objects = []
        page = 0
        db_objects = []
        while page == 0 or len(db_objects) == page_size:
            db_objects = (
                Session.query(model_class)
                .filter(model_class.user_id == self._user.id)
                .order_by(model_class.id)
                .limit(page_size)
                .offset(page * page_size)
                .all()
            )
            objects.extend(db_objects)
            page += 1
        return objects

    def _get_aliases(self) -> List[Alias]:
        return self._get_paginated_model(Alias)

    def _get_mailboxes(self) -> List[Mailbox]:
        return self._get_paginated_model(Mailbox)

    def _get_contacts(self) -> List[Contact]:
        return self._get_paginated_model(Contact)

    def _get_directories(self) -> List[Directory]:
        return self._get_paginated_model(Directory)

    def _get_email_logs(self) -> List[EmailLog]:
        return self._get_paginated_model(EmailLog)

    def _get_domains(self) -> List[CustomDomain]:
        return self._get_paginated_model(CustomDomain)

    def _get_refused_emails(self) -> List[RefusedEmail]:
        return self._get_paginated_model(RefusedEmail)

    @classmethod
    def _model_to_dict(cls, object: Base) -> Dict:
        data = {}
        fields_to_filter = cls.REMOVE_FIELDS.get(object.__class__.__name__, ())
        for column in object.__table__.columns:
            if column.name in fields_to_filter:
                continue
            value = getattr(object, column.name)
            if isinstance(value, arrow.Arrow):
                value = value.isoformat()
            if issubclass(value.__class__, EnumE):
                value = value.value
            data[column.name] = value
        return data

    def _build_zip(self) -> BytesIO:
        memfile = BytesIO()
        with zipfile.ZipFile(memfile, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "user.json", json.dumps(ExportUserDataJob._model_to_dict(self._user))
            )
            for model_name, get_models in [
                ("aliases", self._get_aliases),
                ("mailboxes", self._get_mailboxes),
                ("contacts", self._get_contacts),
                ("directories", self._get_directories),
                ("domains", self._get_domains),
                ("email_logs", self._get_email_logs),
                # not include RefusedEmail as they are not usable by user and are automatically deleted
                # ("refused_emails", self._get_refused_emails),
            ]:
                model_objs = get_models()
                data = json.dumps(
                    [
                        ExportUserDataJob._model_to_dict(model_obj)
                        for model_obj in model_objs
                    ]
                )
                zf.writestr(f"{model_name}.json", data)
        memfile.seek(0)
        return memfile

    def run(self):
        zipped_contents = self._build_zip()

        to_email = self._user.email

        msg = MIMEMultipart()
        msg[headers.SUBJECT] = "Your SimpleLogin data"
        msg[headers.FROM] = f'"SimpleLogin (noreply)" <{config.NOREPLY}>'
        msg[headers.TO] = to_email
        msg.attach(MIMEText(render("transactional/user-report.html"), "html"))
        attachment = MIMEApplication(zipped_contents.read())
        attachment.add_header(
            "Content-Disposition", "attachment", filename="user_report.zip"
        )
        attachment.add_header("Content-Type", "application/zip")
        msg.attach(attachment)

        # add DKIM
        email_domain = config.NOREPLY[config.NOREPLY.find("@") + 1 :]
        add_dkim_signature(msg, email_domain)

        transaction = TransactionalEmail.create(email=to_email, commit=True)
        sl_sendmail(
            generate_verp_email(VerpType.transactional, transaction.id),
            to_email,
            msg,
            ignore_smtp_error=False,
        )

    @staticmethod
    def create_from_job(job: Job) -> Optional[ExportUserDataJob]:
        user = User.get(job.payload["user_id"])
        if not user:
            return None
        return ExportUserDataJob(user)

    def store_job_in_db(self) -> Optional[Job]:
        jobs_in_db = (
            Session.query(Job)
            .filter(
                Job.name == config.JOB_SEND_USER_REPORT,
                Job.payload.op("->")("user_id").cast(sqlalchemy.TEXT)
                == str(self._user.id),
                Job.taken.is_(False),
            )
            .count()
        )
        if jobs_in_db > 0:
            return None
        return Job.create(
            name=config.JOB_SEND_USER_REPORT,
            payload={"user_id": self._user.id},
            run_at=arrow.now(),
            commit=True,
        )
