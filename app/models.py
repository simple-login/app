from __future__ import annotations

import base64
import enum
import hashlib
import hmac
import os
import random
import secrets
import uuid
from typing import List, Tuple, Optional, Union

import arrow
import sqlalchemy as sa
from arrow import Arrow
from email_validator import validate_email
from flanker.addresslib import address
from flask import url_for
from flask_login import UserMixin
from jinja2 import FileSystemLoader, Environment
from sqlalchemy import orm
from sqlalchemy import text, desc, CheckConstraint, Index, Column
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import deferred
from sqlalchemy.sql import and_
from sqlalchemy_utils import ArrowType

from app import config
from app import s3
from app.db import Session
from app.errors import (
    AliasInTrashError,
    DirectoryInTrashError,
    SubdomainInTrashError,
    CannotCreateContactForReverseAlias,
)
from app.handler.unsubscribe_encoder import UnsubscribeAction, UnsubscribeEncoder
from app.log import LOG
from app.oauth_models import Scope
from app.pw_models import PasswordOracle
from app.utils import (
    convert_to_id,
    random_string,
    random_words,
    sanitize_email,
    random_word,
)

Base = declarative_base()

PADDLE_SUBSCRIPTION_GRACE_DAYS = 14
_PARTNER_SUBSCRIPTION_GRACE_DAYS = 14


class TSVector(sa.types.TypeDecorator):
    impl = TSVECTOR


class ModelMixin(object):
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    created_at = sa.Column(ArrowType, default=arrow.utcnow, nullable=False)
    updated_at = sa.Column(ArrowType, default=None, onupdate=arrow.utcnow)

    _repr_hide = ["created_at", "updated_at"]

    @classmethod
    def query(cls):
        return Session.query(cls)

    @classmethod
    def yield_per_query(cls, page=1000):
        """to be used when iterating on a big table to avoid taking all the memory"""
        return Session.query(cls).yield_per(page).enable_eagerloads(False)

    @classmethod
    def get(cls, id):
        return Session.query(cls).get(id)

    @classmethod
    def get_by(cls, **kw):
        return Session.query(cls).filter_by(**kw).first()

    @classmethod
    def filter_by(cls, **kw):
        return Session.query(cls).filter_by(**kw)

    @classmethod
    def filter(cls, *args, **kw):
        return Session.query(cls).filter(*args, **kw)

    @classmethod
    def order_by(cls, *args, **kw):
        return Session.query(cls).order_by(*args, **kw)

    @classmethod
    def all(cls):
        return Session.query(cls).all()

    @classmethod
    def count(cls):
        return Session.query(cls).count()

    @classmethod
    def get_or_create(cls, **kw):
        r = cls.get_by(**kw)
        if not r:
            r = cls(**kw)
            Session.add(r)

        return r

    @classmethod
    def create(cls, **kw):
        # whether to call Session.commit
        commit = kw.pop("commit", False)
        flush = kw.pop("flush", False)

        r = cls(**kw)
        Session.add(r)

        if commit:
            Session.commit()

        if flush:
            Session.flush()

        return r

    def save(self):
        Session.add(self)

    @classmethod
    def delete(cls, obj_id, commit=False):
        Session.query(cls).filter(cls.id == obj_id).delete()

        if commit:
            Session.commit()

    @classmethod
    def first(cls):
        return Session.query(cls).first()

    def __repr__(self):
        values = ", ".join(
            "%s=%r" % (n, getattr(self, n))
            for n in self.__table__.c.keys()
            if n not in self._repr_hide
        )
        return "%s(%s)" % (self.__class__.__name__, values)


class File(Base, ModelMixin):
    __tablename__ = "file"
    path = sa.Column(sa.String(128), unique=True, nullable=False)
    user_id = sa.Column(sa.ForeignKey("users.id", ondelete="cascade"), nullable=True)

    def get_url(self, expires_in=3600):
        return s3.get_url(self.path, expires_in)

    def __repr__(self):
        return f"<File {self.path}>"


class EnumE(enum.Enum):
    @classmethod
    def has_value(cls, value: int) -> bool:
        return value in set(item.value for item in cls)

    @classmethod
    def get_name(cls, value: int) -> Optional[str]:
        for item in cls:
            if item.value == value:
                return item.name

        return None

    @classmethod
    def has_name(cls, name: str) -> bool:
        for item in cls:
            if item.name == name:
                return True

        return False

    @classmethod
    def get_value(cls, name: str) -> Optional[int]:
        for item in cls:
            if item.name == name:
                return item.value

        return None


class PlanEnum(EnumE):
    monthly = 2
    yearly = 3


# Specify the format for sender address
class SenderFormatEnum(EnumE):
    AT = 0  # John Wick - john at wick.com
    A = 2  # John Wick - john(a)wick.com
    NAME_ONLY = 5  # John Wick
    AT_ONLY = 6  # john at wick.com
    NO_NAME = 7


class AliasGeneratorEnum(EnumE):
    word = 1  # aliases are generated based on random words
    uuid = 2  # aliases are generated based on uuid


class AliasSuffixEnum(EnumE):
    word = 0  # Random word from dictionary file
    random_string = 1  # Completely random string


class BlockBehaviourEnum(EnumE):
    return_2xx = 0
    return_5xx = 1


class AuditLogActionEnum(EnumE):
    create_object = 0
    update_object = 1
    delete_object = 2
    manual_upgrade = 3
    extend_trial = 4
    disable_2fa = 5
    logged_as_user = 6
    extend_subscription = 7
    download_provider_complaint = 8


class Phase(EnumE):
    unknown = 0
    forward = 1
    reply = 2


class VerpType(EnumE):
    bounce_forward = 0
    bounce_reply = 1
    transactional = 2


class JobState(EnumE):
    ready = 0
    taken = 1
    done = 2
    error = 3


class UnsubscribeBehaviourEnum(EnumE):
    DisableAlias = 0
    BlockContact = 1
    PreserveOriginal = 2


class IntEnumType(sa.types.TypeDecorator):
    impl = sa.Integer

    def __init__(self, enumtype, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._enum_type = enumtype

    def process_bind_param(self, enum_obj, dialect):
        return enum_obj.value

    def process_result_value(self, enum_value, dialect):
        return self._enum_type(enum_value)


class Hibp(Base, ModelMixin):
    __tablename__ = "hibp"
    name = sa.Column(sa.String(), nullable=False, unique=True, index=True)
    breached_aliases = orm.relationship("Alias", secondary="alias_hibp")

    description = sa.Column(sa.Text)
    date = sa.Column(ArrowType, nullable=True)

    def __repr__(self):
        return f"<HIBP Breach {self.id} {self.name}>"


class HibpNotifiedAlias(Base, ModelMixin):
    """Contain list of aliases that have been notified to users
    So that we can only notify users of new aliases.
    """

    __tablename__ = "hibp_notified_alias"
    alias_id = sa.Column(sa.ForeignKey("alias.id", ondelete="cascade"), nullable=False)
    user_id = sa.Column(sa.ForeignKey("users.id", ondelete="cascade"), nullable=False)

    notified_at = sa.Column(ArrowType, default=arrow.utcnow, nullable=False)


class Fido(Base, ModelMixin):
    __tablename__ = "fido"
    credential_id = sa.Column(sa.String(), nullable=False, unique=True, index=True)
    uuid = sa.Column(
        sa.ForeignKey("users.fido_uuid", ondelete="cascade"),
        unique=False,
        nullable=False,
    )
    public_key = sa.Column(sa.String(), nullable=False, unique=True)
    sign_count = sa.Column(sa.BigInteger(), nullable=False)
    name = sa.Column(sa.String(128), nullable=False, unique=False)
    user_id = sa.Column(sa.ForeignKey("users.id", ondelete="cascade"), nullable=True)


class User(Base, ModelMixin, UserMixin, PasswordOracle):
    __tablename__ = "users"

    FLAG_FREE_DISABLE_CREATE_ALIAS = 1 << 0
    FLAG_CREATED_FROM_PARTNER = 1 << 1
    FLAG_FREE_OLD_ALIAS_LIMIT = 1 << 2

    email = sa.Column(sa.String(256), unique=True, nullable=False)

    name = sa.Column(sa.String(128), nullable=True)
    is_admin = sa.Column(sa.Boolean, nullable=False, default=False)
    alias_generator = sa.Column(
        sa.Integer,
        nullable=False,
        default=AliasGeneratorEnum.word.value,
        server_default=str(AliasGeneratorEnum.word.value),
    )
    notification = sa.Column(
        sa.Boolean, default=True, nullable=False, server_default="1"
    )

    activated = sa.Column(sa.Boolean, default=False, nullable=False)

    # an account can be disabled if having harmful behavior
    disabled = sa.Column(sa.Boolean, default=False, nullable=False, server_default="0")

    profile_picture_id = sa.Column(sa.ForeignKey(File.id), nullable=True)

    otp_secret = sa.Column(sa.String(16), nullable=True)
    enable_otp = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )
    last_otp = sa.Column(sa.String(12), nullable=True, default=False)

    # Fields for WebAuthn
    fido_uuid = sa.Column(sa.String(), nullable=True, unique=True)

    # the default domain that's used when user creates a new random alias
    # default_alias_custom_domain_id XOR default_alias_public_domain_id
    default_alias_custom_domain_id = sa.Column(
        sa.ForeignKey("custom_domain.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    default_alias_public_domain_id = sa.Column(
        sa.ForeignKey("public_domain.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    # some users could have lifetime premium
    lifetime = sa.Column(sa.Boolean, default=False, nullable=False, server_default="0")
    paid_lifetime = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )
    lifetime_coupon_id = sa.Column(
        sa.ForeignKey("lifetime_coupon.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    # user can use all premium features until this date
    trial_end = sa.Column(
        ArrowType, default=lambda: arrow.now().shift(days=7, hours=1), nullable=True
    )

    # the mailbox used when create random alias
    # this field is nullable but in practice, it's always set
    # it cannot be set to non-nullable though
    # as this will create foreign key cycle between User and Mailbox
    default_mailbox_id = sa.Column(
        sa.ForeignKey("mailbox.id"), nullable=True, default=None
    )

    profile_picture = orm.relationship(File, foreign_keys=[profile_picture_id])

    # Specify the format for sender address
    # for the full list, see SenderFormatEnum
    sender_format = sa.Column(
        sa.Integer, default="0", nullable=False, server_default="0"
    )
    # to know whether user has explicitly chosen a sender format as opposed to those who use the default ones.
    # users who haven't chosen a sender format and are using 1 or 3 format, their sender format will be set to 0
    sender_format_updated_at = sa.Column(ArrowType, default=None)

    replace_reverse_alias = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    referral_id = sa.Column(
        sa.ForeignKey("referral.id", ondelete="SET NULL"), nullable=True, default=None
    )

    referral = orm.relationship("Referral", foreign_keys=[referral_id])

    # whether intro has been shown to user
    intro_shown = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    default_mailbox = orm.relationship("Mailbox", foreign_keys=[default_mailbox_id])

    # user can set a more strict max_spam score to block spams more aggressively
    max_spam_score = sa.Column(sa.Integer, nullable=True)

    # newsletter is sent to this address
    newsletter_alias_id = sa.Column(
        sa.ForeignKey("alias.id", ondelete="SET NULL"), nullable=True, default=None
    )

    # whether to include the sender address in reverse-alias
    include_sender_in_reverse_alias = sa.Column(
        sa.Boolean, default=True, nullable=False, server_default="0"
    )

    # whether to use random string or random word as suffix
    # Random word from dictionary file -> 0
    # Completely random string -> 1
    random_alias_suffix = sa.Column(
        sa.Integer,
        nullable=False,
        default=AliasSuffixEnum.random_string.value,
        server_default=str(AliasSuffixEnum.random_string.value),
    )

    # always expand the alias info, i.e. without needing to press "More"
    expand_alias_info = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    # ignore emails send from a mailbox to its alias. This can happen when replying all to a forwarded email
    # can automatically re-includes the alias
    ignore_loop_email = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    # used for flask-login as an "alternative token"
    # cf https://flask-login.readthedocs.io/en/latest/#alternative-tokens
    alternative_id = sa.Column(sa.String(128), unique=True, nullable=True)

    # by default, when an alias is automatically created, a note like "Created with ...." is created
    # If this field is True, the note won't be created.
    disable_automatic_alias_note = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    # By default, the one-click unsubscribe disable the alias
    # If set to true, it will block the sender instead
    one_click_unsubscribe_block_sender = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    # automatically include the website name when user creates an alias via the SimpleLogin icon in the email field
    include_website_in_one_click_alias = sa.Column(
        sa.Boolean,
        # new user will have this option turned on automatically
        default=True,
        nullable=False,
        # old user will have this option turned off
        server_default="0",
    )

    _directory_quota = sa.Column(
        "directory_quota", sa.Integer, default=50, nullable=False, server_default="50"
    )

    _subdomain_quota = sa.Column(
        "subdomain_quota", sa.Integer, default=5, nullable=False, server_default="5"
    )

    # user can use import to import too many aliases
    disable_import = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    # user can use the phone feature
    can_use_phone = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    # in minutes
    phone_quota = sa.Column(sa.Integer, nullable=True)

    # Status code to return if is blocked
    block_behaviour = sa.Column(
        sa.Enum(BlockBehaviourEnum),
        nullable=False,
        server_default=BlockBehaviourEnum.return_2xx.name,
    )

    # to keep existing behavior, the server default is TRUE whereas for new user, the default value is FALSE
    include_header_email_header = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="1"
    )

    # bitwise flags. Allow for future expansion
    flags = sa.Column(
        sa.BigInteger,
        default=FLAG_FREE_DISABLE_CREATE_ALIAS,
        server_default="0",
        nullable=False,
    )

    # Keep original unsub behaviour
    unsub_behaviour = sa.Column(
        IntEnumType(UnsubscribeBehaviourEnum),
        default=UnsubscribeBehaviourEnum.DisableAlias,
        server_default=str(UnsubscribeBehaviourEnum.DisableAlias.value),
        nullable=False,
    )

    @property
    def directory_quota(self):
        return min(
            self._directory_quota,
            config.MAX_NB_DIRECTORY - Directory.filter_by(user_id=self.id).count(),
        )

    @property
    def subdomain_quota(self):
        return min(
            self._subdomain_quota,
            config.MAX_NB_SUBDOMAIN
            - CustomDomain.filter_by(user_id=self.id, is_sl_subdomain=True).count(),
        )

    @property
    def created_by_partner(self):
        return User.FLAG_CREATED_FROM_PARTNER == (
            self.flags & User.FLAG_CREATED_FROM_PARTNER
        )

    @staticmethod
    def subdomain_is_available():
        return SLDomain.filter_by(can_use_subdomain=True).count() > 0

    # implement flask-login "alternative token"
    def get_id(self):
        if self.alternative_id:
            return self.alternative_id
        else:
            return str(self.id)

    @classmethod
    def create(cls, email, name="", password=None, from_partner=False, **kwargs):
        user: User = super(User, cls).create(email=email, name=name, **kwargs)

        if password:
            user.set_password(password)

        Session.flush()

        mb = Mailbox.create(user_id=user.id, email=user.email, verified=True)
        Session.flush()
        user.default_mailbox_id = mb.id

        # create a first alias mail to show user how to use when they login
        alias = Alias.create_new(
            user,
            prefix="simplelogin-newsletter",
            mailbox_id=mb.id,
            note="This is your first alias. It's used to receive SimpleLogin communications "
            "like new features announcements, newsletters.",
        )
        Session.flush()

        user.newsletter_alias_id = alias.id
        Session.flush()

        # generate an alternative_id if needed
        if "alternative_id" not in kwargs:
            user.alternative_id = str(uuid.uuid4())

        # If the user is created from partner, do not notify
        # nor give a trial
        if from_partner:
            user.flags = User.FLAG_CREATED_FROM_PARTNER
            user.notification = False
            user.trial_end = None
            Job.create(
                name=config.JOB_SEND_PROTON_WELCOME_1,
                payload={"user_id": user.id},
                run_at=arrow.now(),
            )
            Session.flush()
            return user

        if config.DISABLE_ONBOARDING:
            LOG.d("Disable onboarding emails")
            return user

        # Schedule onboarding emails
        Job.create(
            name=config.JOB_ONBOARDING_1,
            payload={"user_id": user.id},
            run_at=arrow.now().shift(days=1),
        )
        Job.create(
            name=config.JOB_ONBOARDING_2,
            payload={"user_id": user.id},
            run_at=arrow.now().shift(days=2),
        )
        Job.create(
            name=config.JOB_ONBOARDING_4,
            payload={"user_id": user.id},
            run_at=arrow.now().shift(days=3),
        )
        Session.flush()

        return user

    def get_active_subscription(
        self,
    ) -> Optional[
        Union[
            Subscription
            | AppleSubscription
            | ManualSubscription
            | CoinbaseSubscription
            | PartnerSubscription
        ]
    ]:
        sub: Subscription = self.get_paddle_subscription()
        if sub:
            return sub

        apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=self.id)
        if apple_sub and apple_sub.is_valid():
            return apple_sub

        manual_sub: ManualSubscription = ManualSubscription.get_by(user_id=self.id)
        if manual_sub and manual_sub.is_active():
            return manual_sub

        coinbase_subscription: CoinbaseSubscription = CoinbaseSubscription.get_by(
            user_id=self.id
        )
        if coinbase_subscription and coinbase_subscription.is_active():
            return coinbase_subscription

        partner_sub: PartnerSubscription = PartnerSubscription.find_by_user_id(self.id)
        if partner_sub and partner_sub.is_active():
            return partner_sub

        return None

    # region Billing
    def lifetime_or_active_subscription(self) -> bool:
        """True if user has lifetime licence or active subscription"""
        if self.lifetime:
            return True

        return self.get_active_subscription() is not None

    def is_paid(self) -> bool:
        """same as _lifetime_or_active_subscription but not include free manual subscription"""
        sub = self.get_active_subscription()
        if sub is None:
            return False

        if isinstance(sub, ManualSubscription) and sub.is_giveaway:
            return False

        return True

    def in_trial(self):
        """return True if user does not have lifetime licence or an active subscription AND is in trial period"""
        if self.lifetime_or_active_subscription():
            return False

        if self.trial_end and arrow.now() < self.trial_end:
            return True

        return False

    def should_show_upgrade_button(self):
        if self.lifetime_or_active_subscription():
            return False

        return True

    def is_premium(self) -> bool:
        """
        user is premium if they:
        - have a lifetime deal or
        - in trial period or
        - active subscription
        """
        if self.lifetime_or_active_subscription():
            return True

        if self.trial_end and arrow.now() < self.trial_end:
            return True

        return False

    @property
    def upgrade_channel(self) -> str:
        """Used on admin dashboard"""
        # user can have multiple subscription channel
        channels = []
        if self.lifetime:
            channels.append("Lifetime")

        sub: Subscription = self.get_paddle_subscription()
        if sub:
            if sub.cancelled:
                channels.append(
                    f"""Cancelled Paddle Subscription <a href="https://vendors.paddle.com/subscriptions/customers/manage/{sub.subscription_id}">{sub.subscription_id}</a> {sub.plan_name()} ends at {sub.next_bill_date}"""
                )
            else:
                channels.append(
                    f"""Active Paddle Subscription <a href="https://vendors.paddle.com/subscriptions/customers/manage/{sub.subscription_id}">{sub.subscription_id}</a> {sub.plan_name()}, renews at {sub.next_bill_date}"""
                )

        apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=self.id)
        if apple_sub and apple_sub.is_valid():
            channels.append(f"Apple Subscription {apple_sub.expires_date.humanize()}")

        manual_sub: ManualSubscription = ManualSubscription.get_by(user_id=self.id)
        if manual_sub and manual_sub.is_active():
            mode = "Giveaway" if manual_sub.is_giveaway else "Paid"
            channels.append(
                f"Manual Subscription {manual_sub.comment} {mode} {manual_sub.end_at.humanize()}"
            )

        coinbase_subscription: CoinbaseSubscription = CoinbaseSubscription.get_by(
            user_id=self.id
        )
        if coinbase_subscription and coinbase_subscription.is_active():
            channels.append(
                f"Coinbase Subscription ends {coinbase_subscription.end_at.humanize()}"
            )

        r = (
            Session.query(PartnerSubscription, PartnerUser, Partner)
            .filter(
                PartnerSubscription.partner_user_id == PartnerUser.id,
                PartnerUser.user_id == self.id,
                Partner.id == PartnerUser.partner_id,
            )
            .first()
        )
        if r and r[0].is_active():
            channels.append(
                f"Subscription via {r[2].name} partner , ends {r[0].end_at.humanize()}"
            )

        return ".\n".join(channels)

    # endregion

    def max_alias_for_free_account(self) -> int:
        if (
            self.FLAG_FREE_OLD_ALIAS_LIMIT
            == self.flags & self.FLAG_FREE_OLD_ALIAS_LIMIT
        ):
            return config.MAX_NB_EMAIL_OLD_FREE_PLAN
        else:
            return config.MAX_NB_EMAIL_FREE_PLAN

    def can_create_new_alias(self) -> bool:
        """
        Whether user can create a new alias. User can't create a new alias if
        - has more than 15 aliases in the free plan, *even in the free trial*
        """
        if self.disabled:
            return False

        if self.lifetime_or_active_subscription():
            return True
        else:
            return (
                Alias.filter_by(user_id=self.id).count()
                < self.max_alias_for_free_account()
            )

    def profile_picture_url(self):
        if self.profile_picture_id:
            return self.profile_picture.get_url()
        else:
            return url_for("static", filename="default-avatar.png")

    def suggested_emails(self, website_name) -> (str, [str]):
        """return suggested email and other email choices"""
        website_name = convert_to_id(website_name)

        all_aliases = [
            ge.email for ge in Alias.filter_by(user_id=self.id, enabled=True)
        ]
        if self.can_create_new_alias():
            suggested_alias = Alias.create_new(self, prefix=website_name).email
        else:
            # pick an email from the list of gen emails
            suggested_alias = random.choice(all_aliases)

        return (
            suggested_alias,
            list(set(all_aliases).difference({suggested_alias})),
        )

    def suggested_names(self) -> (str, [str]):
        """return suggested name and other name choices"""
        other_name = convert_to_id(self.name)

        return self.name, [other_name, "Anonymous", "whoami"]

    def get_name_initial(self) -> str:
        if not self.name:
            return ""
        names = self.name.split(" ")
        return "".join([n[0].upper() for n in names if n])

    def get_paddle_subscription(self) -> Optional["Subscription"]:
        """return *active* Paddle subscription
        Return None if the subscription is already expired
        TODO: support user unsubscribe and re-subscribe
        """
        sub = Subscription.get_by(user_id=self.id)

        if sub:
            # grace period is 14 days
            # sub is active until the next billing_date + PADDLE_SUBSCRIPTION_GRACE_DAYS
            if (
                sub.next_bill_date
                >= arrow.now().shift(days=-PADDLE_SUBSCRIPTION_GRACE_DAYS).date()
            ):
                return sub
            # past subscription, user is considered not having a subscription = free plan
            else:
                return None
        else:
            return sub

    def verified_custom_domains(self) -> List["CustomDomain"]:
        return CustomDomain.filter_by(user_id=self.id, ownership_verified=True).all()

    def mailboxes(self) -> List["Mailbox"]:
        """list of mailbox that user own"""
        mailboxes = []

        for mailbox in Mailbox.filter_by(user_id=self.id, verified=True):
            mailboxes.append(mailbox)

        return mailboxes

    def nb_directory(self):
        return Directory.filter_by(user_id=self.id).count()

    def has_custom_domain(self):
        return CustomDomain.filter_by(user_id=self.id, verified=True).count() > 0

    def custom_domains(self):
        return CustomDomain.filter_by(user_id=self.id, verified=True).all()

    def available_domains_for_random_alias(self) -> List[Tuple[bool, str]]:
        """Return available domains for user to create random aliases
        Each result record contains:
        - whether the domain belongs to SimpleLogin
        - the domain
        """
        res = []
        for domain in self.available_sl_domains():
            res.append((True, domain))

        for custom_domain in self.verified_custom_domains():
            res.append((False, custom_domain.domain))

        return res

    def default_random_alias_domain(self) -> str:
        """return the domain used for the random alias"""
        if self.default_alias_custom_domain_id:
            custom_domain = CustomDomain.get(self.default_alias_custom_domain_id)
            # sanity check
            if (
                not custom_domain
                or not custom_domain.verified
                or custom_domain.user_id != self.id
            ):
                LOG.w("Problem with %s default random alias domain", self)
                return config.FIRST_ALIAS_DOMAIN

            return custom_domain.domain

        if self.default_alias_public_domain_id:
            sl_domain = SLDomain.get(self.default_alias_public_domain_id)
            # sanity check
            if not sl_domain:
                LOG.e("Problem with %s public random alias domain", self)
                return config.FIRST_ALIAS_DOMAIN

            if sl_domain.premium_only and not self.is_premium():
                LOG.w(
                    "%s is not premium and cannot use %s. Reset default random alias domain setting",
                    self,
                    sl_domain,
                )
                self.default_alias_custom_domain_id = None
                self.default_alias_public_domain_id = None
                Session.commit()
                return config.FIRST_ALIAS_DOMAIN

            return sl_domain.domain

        return config.FIRST_ALIAS_DOMAIN

    def fido_enabled(self) -> bool:
        if self.fido_uuid is not None:
            return True
        return False

    def two_factor_authentication_enabled(self) -> bool:
        return self.enable_otp or self.fido_enabled()

    def get_communication_email(self) -> (Optional[str], str, bool):
        """
        Return
        - the email that user uses to receive email communication. None if user unsubscribes from newsletter
        - the unsubscribe URL
        - whether the unsubscribe method is via sending email (mailto:) or Http POST
        """
        if self.notification and self.activated and not self.disabled:
            if self.newsletter_alias_id:
                alias = Alias.get(self.newsletter_alias_id)
                if alias.enabled:
                    unsub = UnsubscribeEncoder.encode(
                        UnsubscribeAction.DisableAlias, alias.id
                    )
                    return alias.email, unsub.link, unsub.via_email
                # alias disabled -> user doesn't want to receive newsletter
                else:
                    return None, None, False
            else:
                # do not handle http POST unsubscribe
                if config.UNSUBSCRIBER:
                    # use * as suffix instead of = as for alias unsubscribe
                    return (
                        self.email,
                        UnsubscribeEncoder.encode_mailto(
                            UnsubscribeAction.UnsubscribeNewsletter, self.id
                        ),
                        True,
                    )

        return None, None, False

    def available_sl_domains(self) -> [str]:
        """
        Return all SimpleLogin domains that user can use when creating a new alias, including:
        - SimpleLogin public domains, available for all users (ALIAS_DOMAIN)
        - SimpleLogin premium domains, only available for Premium accounts (PREMIUM_ALIAS_DOMAIN)
        """
        return [sl_domain.domain for sl_domain in self.get_sl_domains()]

    def get_sl_domains(self) -> List["SLDomain"]:
        query = SLDomain.filter_by(hidden=False).order_by(SLDomain.order)

        if self.is_premium():
            return query.all()
        else:
            return query.filter_by(premium_only=False).all()

    def available_alias_domains(self) -> [str]:
        """return all domains that user can use when creating a new alias, including:
        - SimpleLogin public domains, available for all users (ALIAS_DOMAIN)
        - SimpleLogin premium domains, only available for Premium accounts (PREMIUM_ALIAS_DOMAIN)
        - Verified custom domains

        """
        domains = self.available_sl_domains()

        for custom_domain in self.verified_custom_domains():
            domains.append(custom_domain.domain)

        # can have duplicate where a "root" user has a domain that's also listed in SL domains
        return list(set(domains))

    def should_show_app_page(self) -> bool:
        """whether to show the app page"""
        return (
            # when user has used the "Sign in with SL" button before
            ClientUser.filter(ClientUser.user_id == self.id).count()
            # or when user has created an app
            + Client.filter(Client.user_id == self.id).count()
            > 0
        )

    def get_random_alias_suffix(self):
        """Get random suffix for an alias based on user's preference.


        Returns:
            str: the random suffix generated
        """
        if self.random_alias_suffix == AliasSuffixEnum.random_string.value:
            return random_string(config.ALIAS_RANDOM_SUFFIX_LENGTH, include_digits=True)
        return random_word()

    def __repr__(self):
        return f"<User {self.id} {self.name} {self.email}>"


def _expiration_1h():
    return arrow.now().shift(hours=1)


def _expiration_12h():
    return arrow.now().shift(hours=12)


def _expiration_5m():
    return arrow.now().shift(minutes=5)


def _expiration_7d():
    return arrow.now().shift(days=7)


class ActivationCode(Base, ModelMixin):
    """For activate user account"""

    __tablename__ = "activation_code"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    code = sa.Column(sa.String(128), unique=True, nullable=False)

    user = orm.relationship(User)

    expired = sa.Column(ArrowType, nullable=False, default=_expiration_1h)

    def is_expired(self):
        return self.expired < arrow.now()


class ResetPasswordCode(Base, ModelMixin):
    """For resetting password"""

    __tablename__ = "reset_password_code"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    code = sa.Column(sa.String(128), unique=True, nullable=False)

    user = orm.relationship(User)

    expired = sa.Column(ArrowType, nullable=False, default=_expiration_1h)

    def is_expired(self):
        return self.expired < arrow.now()


class SocialAuth(Base, ModelMixin):
    """Store how user authenticates with social login"""

    __tablename__ = "social_auth"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    # name of the social login used, could be facebook, google or github
    social = sa.Column(sa.String(128), nullable=False)

    __table_args__ = (sa.UniqueConstraint("user_id", "social", name="uq_social_auth"),)


# <<< OAUTH models >>>


def generate_oauth_client_id(client_name) -> str:
    oauth_client_id = convert_to_id(client_name) + "-" + random_string()

    # check that the client does not exist yet
    if not Client.get_by(oauth_client_id=oauth_client_id):
        LOG.d("generate oauth_client_id %s", oauth_client_id)
        return oauth_client_id

    # Rerun the function
    LOG.w("client_id %s already exists, generate a new client_id", oauth_client_id)
    return generate_oauth_client_id(client_name)


class MfaBrowser(Base, ModelMixin):
    __tablename__ = "mfa_browser"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    token = sa.Column(sa.String(64), default=False, unique=True, nullable=False)
    expires = sa.Column(ArrowType, default=False, nullable=False)

    user = orm.relationship(User)

    @classmethod
    def create_new(cls, user, token_length=64) -> "MfaBrowser":
        found = False
        while not found:
            token = random_string(token_length)

            if not cls.get_by(token=token):
                found = True

        return MfaBrowser.create(
            user_id=user.id,
            token=token,
            expires=arrow.now().shift(days=30),
        )

    @classmethod
    def delete(cls, token):
        cls.filter(cls.token == token).delete()
        Session.commit()

    @classmethod
    def delete_expired(cls):
        cls.filter(cls.expires < arrow.now()).delete()
        Session.commit()

    def is_expired(self):
        return self.expires < arrow.now()

    def reset_expire(self):
        self.expires = arrow.now().shift(days=30)


class Client(Base, ModelMixin):
    __tablename__ = "client"
    oauth_client_id = sa.Column(sa.String(128), unique=True, nullable=False)
    oauth_client_secret = sa.Column(sa.String(128), nullable=False)

    name = sa.Column(sa.String(128), nullable=False)
    home_url = sa.Column(sa.String(1024))

    # user who created this client
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    icon_id = sa.Column(sa.ForeignKey(File.id), nullable=True)

    # an app needs to be approved by SimpleLogin team
    approved = sa.Column(sa.Boolean, nullable=False, default=False, server_default="0")
    description = sa.Column(sa.Text, nullable=True)

    # a referral can be attached to a client
    # so all users who sign up via the authorize screen are counted towards this referral
    referral_id = sa.Column(
        sa.ForeignKey("referral.id", ondelete="SET NULL"), nullable=True
    )

    icon = orm.relationship(File)
    user = orm.relationship(User)
    referral = orm.relationship("Referral")

    def nb_user(self):
        return ClientUser.filter_by(client_id=self.id).count()

    def get_scopes(self) -> [Scope]:
        # todo: client can choose which scopes they want to have access
        return [Scope.NAME, Scope.EMAIL, Scope.AVATAR_URL]

    @classmethod
    def create_new(cls, name, user_id) -> "Client":
        # generate a client-id
        oauth_client_id = generate_oauth_client_id(name)
        oauth_client_secret = random_string(40)
        client = Client.create(
            name=name,
            oauth_client_id=oauth_client_id,
            oauth_client_secret=oauth_client_secret,
            user_id=user_id,
        )

        return client

    def get_icon_url(self):
        if self.icon_id:
            return self.icon.get_url()
        else:
            return config.URL + "/static/default-icon.svg"

    def last_user_login(self) -> "ClientUser":
        client_user = (
            ClientUser.filter(ClientUser.client_id == self.id)
            .order_by(ClientUser.updated_at)
            .first()
        )
        if client_user:
            return client_user
        return None


class RedirectUri(Base, ModelMixin):
    """Valid redirect uris for a client"""

    __tablename__ = "redirect_uri"

    client_id = sa.Column(sa.ForeignKey(Client.id, ondelete="cascade"), nullable=False)
    uri = sa.Column(sa.String(1024), nullable=False)

    client = orm.relationship(Client, backref="redirect_uris")


class AuthorizationCode(Base, ModelMixin):
    __tablename__ = "authorization_code"

    code = sa.Column(sa.String(128), unique=True, nullable=False)
    client_id = sa.Column(sa.ForeignKey(Client.id, ondelete="cascade"), nullable=False)
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    scope = sa.Column(sa.String(128))
    redirect_uri = sa.Column(sa.String(1024))

    # what is the input response_type, e.g. "code", "code,id_token", ...
    response_type = sa.Column(sa.String(128))

    nonce = sa.Column(sa.Text, nullable=True, default=None, server_default=text("NULL"))

    user = orm.relationship(User, lazy=False)
    client = orm.relationship(Client, lazy=False)

    expired = sa.Column(ArrowType, nullable=False, default=_expiration_5m)

    def is_expired(self):
        return self.expired < arrow.now()


class OauthToken(Base, ModelMixin):
    __tablename__ = "oauth_token"

    access_token = sa.Column(sa.String(128), unique=True)
    client_id = sa.Column(sa.ForeignKey(Client.id, ondelete="cascade"), nullable=False)
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    scope = sa.Column(sa.String(128))
    redirect_uri = sa.Column(sa.String(1024))

    # what is the input response_type, e.g. "token", "token,id_token", ...
    response_type = sa.Column(sa.String(128))

    user = orm.relationship(User)
    client = orm.relationship(Client)

    expired = sa.Column(ArrowType, nullable=False, default=_expiration_1h)

    def is_expired(self):
        return self.expired < arrow.now()


def generate_email(
    scheme: int = AliasGeneratorEnum.word.value,
    in_hex: bool = False,
    alias_domain=config.FIRST_ALIAS_DOMAIN,
) -> str:
    """generate an email address that does not exist before
    :param alias_domain: the domain used to generate the alias.
    :param scheme: int, value of AliasGeneratorEnum, indicate how the email is generated
    :type in_hex: bool, if the generate scheme is uuid, is hex favorable?
    """
    if scheme == AliasGeneratorEnum.uuid.value:
        name = uuid.uuid4().hex if in_hex else uuid.uuid4().__str__()
        random_email = name + "@" + alias_domain
    else:
        random_email = random_words() + "@" + alias_domain

    random_email = random_email.lower().strip()

    # check that the client does not exist yet
    if not Alias.get_by(email=random_email) and not DeletedAlias.get_by(
        email=random_email
    ):
        LOG.d("generate email %s", random_email)
        return random_email

    # Rerun the function
    LOG.w("email %s already exists, generate a new email", random_email)
    return generate_email(scheme=scheme, in_hex=in_hex)


class Alias(Base, ModelMixin):
    __tablename__ = "alias"
    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, index=True
    )
    email = sa.Column(sa.String(128), unique=True, nullable=False)

    # the name to use when user replies/sends from alias
    name = sa.Column(sa.String(128), nullable=True, default=None)

    enabled = sa.Column(sa.Boolean(), default=True, nullable=False)

    custom_domain_id = sa.Column(
        sa.ForeignKey("custom_domain.id", ondelete="cascade"), nullable=True, index=True
    )

    custom_domain = orm.relationship("CustomDomain", foreign_keys=[custom_domain_id])

    # To know whether an alias is created "on the fly", i.e. via the custom domain catch-all feature
    automatic_creation = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # to know whether an alias belongs to a directory
    directory_id = sa.Column(
        sa.ForeignKey("directory.id", ondelete="cascade"), nullable=True, index=True
    )

    note = sa.Column(sa.Text, default=None, nullable=True)

    # an alias can be owned by another mailbox
    mailbox_id = sa.Column(
        sa.ForeignKey("mailbox.id", ondelete="cascade"), nullable=False, index=True
    )

    # prefix _ to avoid this object being used accidentally.
    # To have the list of all mailboxes, should use AliasInfo instead
    _mailboxes = orm.relationship("Mailbox", secondary="alias_mailbox", lazy="joined")

    # If the mailbox has PGP-enabled, user can choose disable the PGP on the alias
    # this is useful when some senders already support PGP
    disable_pgp = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # a way to bypass the bounce automatic disable mechanism
    cannot_be_disabled = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # when a mailbox wants to send an email on behalf of the alias via the reverse-alias
    # several checks are performed to avoid email spoofing
    # this option allow disabling these checks
    disable_email_spoofing_check = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # to know whether an alias is added using a batch import
    batch_import_id = sa.Column(
        sa.ForeignKey("batch_import.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    # set in case of alias transfer.
    original_owner_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="SET NULL"), nullable=True
    )

    # alias is pinned on top
    pinned = sa.Column(sa.Boolean, nullable=False, default=False, server_default="0")

    # used to transfer an alias to another user
    transfer_token = sa.Column(sa.String(64), default=None, unique=True, nullable=True)
    transfer_token_expiration = sa.Column(
        ArrowType, default=arrow.utcnow, nullable=True
    )

    # have I been pwned
    hibp_last_check = sa.Column(ArrowType, default=None)
    hibp_breaches = orm.relationship("Hibp", secondary="alias_hibp")

    # to use Postgres full text search. Only applied on "note" column for now
    # this is a generated Postgres column
    ts_vector = sa.Column(
        TSVector(), sa.Computed("to_tsvector('english', note)", persisted=True)
    )

    __table_args__ = (
        Index("ix_video___ts_vector__", ts_vector, postgresql_using="gin"),
        # index on note column using pg_trgm
        Index(
            "note_pg_trgm_index",
            "note",
            postgresql_ops={"note": "gin_trgm_ops"},
            postgresql_using="gin",
        ),
    )

    user = orm.relationship(User, foreign_keys=[user_id])
    mailbox = orm.relationship("Mailbox", lazy="joined")

    @property
    def mailboxes(self):
        ret = [self.mailbox]
        for m in self._mailboxes:
            ret.append(m)

        ret = [mb for mb in ret if mb.verified]
        ret = sorted(ret, key=lambda mb: mb.email)

        return ret

    def authorized_addresses(self) -> [str]:
        """return addresses that can send on behalf of this alias, i.e. can send emails to this alias's reverse-aliases
        Including its mailboxes and their authorized addresses
        """
        mailboxes = self.mailboxes
        ret = [mb.email for mb in mailboxes]
        for mailbox in mailboxes:
            for aa in mailbox.authorized_addresses:
                ret.append(aa.email)

        return ret

    def mailbox_support_pgp(self) -> bool:
        """return True of one of the mailboxes support PGP"""
        for mb in self.mailboxes:
            if mb.pgp_enabled():
                return True
        return False

    def pgp_enabled(self) -> bool:
        if self.mailbox_support_pgp() and not self.disable_pgp:
            return True
        return False

    @staticmethod
    def get_custom_domain(alias_address) -> Optional["CustomDomain"]:
        alias_domain = validate_email(
            alias_address, check_deliverability=False, allow_smtputf8=False
        ).domain

        # handle the case a SLDomain is also a CustomDomain
        if SLDomain.get_by(domain=alias_domain) is None:
            custom_domain = CustomDomain.get_by(domain=alias_domain)
            if custom_domain:
                return custom_domain

    @classmethod
    def create(cls, **kw):
        commit = kw.pop("commit", False)
        flush = kw.pop("flush", False)

        new_alias = cls(**kw)

        email = kw["email"]
        # make sure email is lowercase and doesn't have any whitespace
        email = sanitize_email(email)

        # make sure alias is not in global trash, i.e. DeletedAlias table
        if DeletedAlias.get_by(email=email):
            raise AliasInTrashError

        if DomainDeletedAlias.get_by(email=email):
            raise AliasInTrashError

        # detect whether alias should belong to a custom domain
        if "custom_domain_id" not in kw:
            custom_domain = Alias.get_custom_domain(email)
            if custom_domain:
                new_alias.custom_domain_id = custom_domain.id

        Session.add(new_alias)
        DailyMetric.get_or_create_today_metric().nb_alias += 1

        if commit:
            Session.commit()

        if flush:
            Session.flush()

        return new_alias

    @classmethod
    def create_new(cls, user, prefix, note=None, mailbox_id=None):
        prefix = prefix.lower().strip().replace(" ", "")

        if not prefix:
            raise Exception("alias prefix cannot be empty")

        # find the right suffix - avoid infinite loop by running this at max 1000 times
        for _ in range(1000):
            suffix = user.get_random_alias_suffix()
            email = f"{prefix}.{suffix}@{config.FIRST_ALIAS_DOMAIN}"

            if not cls.get_by(email=email) and not DeletedAlias.get_by(email=email):
                break

        return Alias.create(
            user_id=user.id,
            email=email,
            note=note,
            mailbox_id=mailbox_id or user.default_mailbox_id,
        )

    @classmethod
    def delete(cls, obj_id):
        raise Exception("should use delete_alias(alias,user) instead")

    @classmethod
    def create_new_random(
        cls,
        user,
        scheme: int = AliasGeneratorEnum.word.value,
        in_hex: bool = False,
        note: str = None,
    ):
        """create a new random alias"""
        custom_domain = None

        random_email = None

        if user.default_alias_custom_domain_id:
            custom_domain = CustomDomain.get(user.default_alias_custom_domain_id)
            random_email = generate_email(
                scheme=scheme, in_hex=in_hex, alias_domain=custom_domain.domain
            )
        elif user.default_alias_public_domain_id:
            sl_domain: SLDomain = SLDomain.get(user.default_alias_public_domain_id)
            if sl_domain.premium_only and not user.is_premium():
                LOG.w("%s not premium, cannot use %s", user, sl_domain)
            else:
                random_email = generate_email(
                    scheme=scheme, in_hex=in_hex, alias_domain=sl_domain.domain
                )

        if not random_email:
            random_email = generate_email(scheme=scheme, in_hex=in_hex)

        alias = Alias.create(
            user_id=user.id,
            email=random_email,
            mailbox_id=user.default_mailbox_id,
            note=note,
        )

        if custom_domain:
            alias.custom_domain_id = custom_domain.id

        return alias

    def mailbox_email(self):
        if self.mailbox_id:
            return self.mailbox.email
        else:
            return self.user.email

    def __repr__(self):
        return f"<Alias {self.id} {self.email}>"


class ClientUser(Base, ModelMixin):
    __tablename__ = "client_user"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "client_id", name="uq_client_user"),
    )

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    client_id = sa.Column(sa.ForeignKey(Client.id, ondelete="cascade"), nullable=False)

    # Null means client has access to user original email
    alias_id = sa.Column(sa.ForeignKey(Alias.id, ondelete="cascade"), nullable=True)

    # user can decide to send to client another name
    name = sa.Column(
        sa.String(128), nullable=True, default=None, server_default=text("NULL")
    )

    # user can decide to send to client a default avatar
    default_avatar = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    alias = orm.relationship(Alias, backref="client_users")

    user = orm.relationship(User)
    client = orm.relationship(Client)

    def get_email(self):
        return self.alias.email if self.alias_id else self.user.email

    def get_user_name(self):
        if self.name:
            return self.name
        else:
            return self.user.name

    def get_user_info(self) -> dict:
        """return user info according to client scope
        Return dict with key being scope name. For now all the fields are the same for all clients:

        {
          "client": "Demo",
          "email": "test-avk5l@mail-tester.com",
          "email_verified": true,
          "id": 1,
          "name": "Son GM",
          "avatar_url": "http://s3..."
        }

        """
        res = {
            "id": self.id,
            "client": self.client.name,
            "email_verified": True,
            "sub": str(self.id),
        }

        for scope in self.client.get_scopes():
            if scope == Scope.NAME:
                if self.name:
                    res[Scope.NAME.value] = self.name or ""
                else:
                    res[Scope.NAME.value] = self.user.name or ""
            elif scope == Scope.AVATAR_URL:
                if self.user.profile_picture_id:
                    if self.default_avatar:
                        res[Scope.AVATAR_URL.value] = (
                            config.URL + "/static/default-avatar.png"
                        )
                    else:
                        res[Scope.AVATAR_URL.value] = self.user.profile_picture.get_url(
                            config.AVATAR_URL_EXPIRATION
                        )
                else:
                    res[Scope.AVATAR_URL.value] = None
            elif scope == Scope.EMAIL:
                # Use generated email
                if self.alias_id:
                    LOG.d(
                        "Use gen email for user %s, client %s", self.user, self.client
                    )
                    res[Scope.EMAIL.value] = self.alias.email
                # Use user original email
                else:
                    res[Scope.EMAIL.value] = self.user.email

        return res


class Contact(Base, ModelMixin):
    """
    Store configuration of sender (website-email) and alias.
    """

    __tablename__ = "contact"

    __table_args__ = (
        sa.UniqueConstraint("alias_id", "website_email", name="uq_contact"),
    )

    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, index=True
    )
    alias_id = sa.Column(
        sa.ForeignKey(Alias.id, ondelete="cascade"), nullable=False, index=True
    )

    name = sa.Column(
        sa.String(512), nullable=True, default=None, server_default=text("NULL")
    )

    website_email = sa.Column(sa.String(512), nullable=False)

    # the email from header, e.g. AB CD <ab@cd.com>
    # nullable as this field is added after website_email
    website_from = sa.Column(sa.String(1024), nullable=True)

    # when user clicks on "reply", they will reply to this address.
    # This address allows to hide user personal email
    # this reply email is created every time a website sends an email to user
    # it used to have the prefix "reply+" or "ra+"
    reply_email = sa.Column(sa.String(512), nullable=False, index=True)

    # whether a contact is created via CC
    is_cc = sa.Column(sa.Boolean, nullable=False, default=False, server_default="0")

    pgp_public_key = sa.Column(sa.Text, nullable=True)
    pgp_finger_print = sa.Column(sa.String(512), nullable=True)

    alias = orm.relationship(Alias, backref="contacts")
    user = orm.relationship(User)

    # the latest reply sent to this contact
    latest_reply: Optional[Arrow] = None

    # to investigate why the website_email is sometimes not correctly parsed
    # the envelope mail_from
    mail_from = sa.Column(sa.Text, nullable=True, default=None)

    # a contact can have an empty email address, in this case it can't receive emails
    invalid_email = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # emails sent from this contact will be blocked
    block_forward = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # whether contact is created automatically during the forward phase
    automatic_created = sa.Column(sa.Boolean, nullable=True, default=False)

    @property
    def email(self):
        return self.website_email

    @classmethod
    def create(cls, **kw):
        commit = kw.pop("commit", False)
        flush = kw.pop("flush", False)

        new_contact = cls(**kw)

        website_email = kw["website_email"]
        # make sure email is lowercase and doesn't have any whitespace
        website_email = sanitize_email(website_email)

        # make sure contact.website_email isn't a reverse alias
        if website_email != config.NOREPLY:
            orig_contact = Contact.get_by(reply_email=website_email)
            if orig_contact:
                raise CannotCreateContactForReverseAlias(str(orig_contact))

        Session.add(new_contact)

        if commit:
            Session.commit()

        if flush:
            Session.flush()

        return new_contact

    def website_send_to(self):
        """return the email address with name.
        to use when user wants to send an email from the alias
        Return
        "First Last | email at example.com" <reverse-alias@SL>
        """

        # Prefer using contact name if possible
        user = self.user
        name = self.name
        email = self.website_email

        if (
            not user
            or not SenderFormatEnum.has_value(user.sender_format)
            or user.sender_format == SenderFormatEnum.AT.value
        ):
            email = email.replace("@", " at ")
        elif user.sender_format == SenderFormatEnum.A.value:
            email = email.replace("@", "(a)")

        # if no name, try to parse it from website_from
        if not name and self.website_from:
            try:
                name = address.parse(self.website_from).display_name
            except Exception:
                # Skip if website_from is wrongly formatted
                LOG.e(
                    "Cannot parse contact %s website_from %s", self, self.website_from
                )
                name = ""

        # remove all double quote
        if name:
            name = name.replace('"', "")

        if name:
            name = name + " | " + email
        else:
            name = email

        # cannot use formataddr here as this field is for email client, not for MTA
        return f'"{name}" <{self.reply_email}>'

    def new_addr(self):
        """
        Replace original email by reply_email. Possible formats:
        - First Last - first at example.com <reply_email> OR
        - First Last - first(a)example.com <reply_email> OR
        - First Last <reply_email>
        - first at example.com <reply_email>
        - reply_email
        And return new address with RFC 2047 format
        """
        user = self.user
        sender_format = user.sender_format if user else SenderFormatEnum.AT.value

        if sender_format == SenderFormatEnum.NO_NAME.value:
            return self.reply_email

        if sender_format == SenderFormatEnum.NAME_ONLY.value:
            new_name = self.name
        elif sender_format == SenderFormatEnum.AT_ONLY.value:
            new_name = self.website_email.replace("@", " at ").strip()
        elif sender_format == SenderFormatEnum.AT.value:
            formatted_email = self.website_email.replace("@", " at ").strip()
            new_name = (
                (self.name + " - " + formatted_email)
                if self.name and self.name != self.website_email.strip()
                else formatted_email
            )
        else:  # SenderFormatEnum.A.value
            formatted_email = self.website_email.replace("@", "(a)").strip()
            new_name = (
                (self.name + " - " + formatted_email)
                if self.name and self.name != self.website_email.strip()
                else formatted_email
            )

        from app.email_utils import sl_formataddr

        new_addr = sl_formataddr((new_name, self.reply_email)).strip()
        return new_addr.strip()

    def last_reply(self) -> "EmailLog":
        """return the most recent reply"""
        return (
            EmailLog.filter_by(contact_id=self.id, is_reply=True)
            .order_by(desc(EmailLog.created_at))
            .first()
        )

    def __repr__(self):
        return f"<Contact {self.id} {self.website_email} {self.alias_id}>"


class EmailLog(Base, ModelMixin):
    __tablename__ = "email_log"

    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, index=True
    )
    contact_id = sa.Column(
        sa.ForeignKey(Contact.id, ondelete="cascade"), nullable=False, index=True
    )
    alias_id = sa.Column(
        sa.ForeignKey(Alias.id, ondelete="cascade"), nullable=True, index=True
    )

    # whether this is a reply
    is_reply = sa.Column(sa.Boolean, nullable=False, default=False)

    # for ex if alias is disabled, this forwarding is blocked
    blocked = sa.Column(sa.Boolean, nullable=False, default=False)

    # can happen when user mailbox refuses the forwarded email
    # usually because the forwarded email is too spammy
    bounced = sa.Column(sa.Boolean, nullable=False, default=False, server_default="0")

    # happen when an email with auto (holiday) reply
    auto_replied = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # SpamAssassin result
    is_spam = sa.Column(sa.Boolean, nullable=False, default=False, server_default="0")
    spam_score = sa.Column(sa.Float, nullable=True)
    spam_status = sa.Column(sa.Text, nullable=True, default=None)
    # do not load this column
    spam_report = deferred(sa.Column(sa.JSON, nullable=True))

    # Point to the email that has been refused
    refused_email_id = sa.Column(
        sa.ForeignKey("refused_email.id", ondelete="SET NULL"), nullable=True
    )

    # in forward phase, this is the mailbox that will receive the email
    # in reply phase, this is the mailbox (or a mailbox's authorized address) that sends the email
    mailbox_id = sa.Column(
        sa.ForeignKey("mailbox.id", ondelete="cascade"), nullable=True
    )

    # in case of bounce, record on what mailbox the email has been bounced
    # useful when an alias has several mailboxes
    bounced_mailbox_id = sa.Column(
        sa.ForeignKey("mailbox.id", ondelete="cascade"), nullable=True
    )

    # the Message ID
    message_id = deferred(sa.Column(sa.String(1024), nullable=True))
    # in the reply phase, the original message_id is replaced by the SL message_id
    sl_message_id = deferred(sa.Column(sa.String(512), nullable=True))

    refused_email = orm.relationship("RefusedEmail")
    forward = orm.relationship(Contact)

    contact = orm.relationship(Contact, backref="email_logs")
    alias = orm.relationship(Alias)
    mailbox = orm.relationship("Mailbox", lazy="joined", foreign_keys=[mailbox_id])
    user = orm.relationship(User)

    def bounced_mailbox(self) -> str:
        if self.bounced_mailbox_id:
            return Mailbox.get(self.bounced_mailbox_id).email
        # retro-compatibility
        return self.contact.alias.mailboxes[0].email

    def get_action(self) -> str:
        """return the action name: forward|reply|block|bounced"""
        if self.is_reply:
            return "reply"
        elif self.bounced:
            return "bounced"
        elif self.blocked:
            return "block"
        else:
            return "forward"

    def get_phase(self) -> str:
        if self.is_reply:
            return "reply"
        else:
            return "forward"

    def get_dashboard_url(self):
        return f"{config.URL}/dashboard/refused_email?highlight_id={self.id}"

    def __repr__(self):
        return f"<EmailLog {self.id}>"


class Subscription(Base, ModelMixin):
    """Paddle subscription"""

    __tablename__ = "subscription"

    # Come from Paddle
    cancel_url = sa.Column(sa.String(1024), nullable=False)
    update_url = sa.Column(sa.String(1024), nullable=False)
    subscription_id = sa.Column(sa.String(1024), nullable=False, unique=True)
    event_time = sa.Column(ArrowType, nullable=False)
    next_bill_date = sa.Column(sa.Date, nullable=False)

    cancelled = sa.Column(sa.Boolean, nullable=False, default=False)

    plan = sa.Column(sa.Enum(PlanEnum), nullable=False)

    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )

    user = orm.relationship(User)

    def plan_name(self):
        if self.plan == PlanEnum.monthly:
            return "Monthly"
        else:
            return "Yearly"

    def __repr__(self):
        return f"<Subscription {self.plan} {self.next_bill_date}>"


class ManualSubscription(Base, ModelMixin):
    """
    For users who use other forms of payment and therefore not pass by Paddle
    """

    __tablename__ = "manual_subscription"

    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )

    # an reminder is sent several days before the subscription ends
    end_at = sa.Column(ArrowType, nullable=False)

    # for storing note about this subscription
    comment = sa.Column(sa.Text, nullable=True)

    # manual subscription are also used for Premium giveaways
    is_giveaway = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    user = orm.relationship(User)

    def is_active(self):
        return self.end_at > arrow.now()


class CoinbaseSubscription(Base, ModelMixin):
    """
    For subscriptions using Coinbase Commerce
    """

    __tablename__ = "coinbase_subscription"

    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )

    # an reminder is sent several days before the subscription ends
    end_at = sa.Column(ArrowType, nullable=False)

    # the Coinbase code
    code = sa.Column(sa.String(64), nullable=True)

    user = orm.relationship(User)

    def is_active(self):
        return self.end_at > arrow.now()


# https://help.apple.com/app-store-connect/#/dev58bda3212
_APPLE_GRACE_PERIOD_DAYS = 16


class AppleSubscription(Base, ModelMixin):
    """
    For users who have subscribed via Apple in-app payment
    """

    __tablename__ = "apple_subscription"

    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )

    expires_date = sa.Column(ArrowType, nullable=False)

    # to avoid using "Restore Purchase" on another account
    original_transaction_id = sa.Column(sa.String(256), nullable=False, unique=True)
    receipt_data = sa.Column(sa.Text(), nullable=False)

    plan = sa.Column(sa.Enum(PlanEnum), nullable=False)

    # to know what subscription user has bought
    # e.g. io.simplelogin.ios_app.subscription.premium.monthly
    product_id = sa.Column(sa.String(256), nullable=True)

    user = orm.relationship(User)

    def is_valid(self):
        return self.expires_date > arrow.now().shift(days=-_APPLE_GRACE_PERIOD_DAYS)


class DeletedAlias(Base, ModelMixin):
    """Store all deleted alias to make sure they are NOT reused"""

    __tablename__ = "deleted_alias"

    email = sa.Column(sa.String(256), unique=True, nullable=False)

    @classmethod
    def create(cls, **kw):
        raise Exception("should use delete_alias(alias,user) instead")

    def __repr__(self):
        return f"<Deleted Alias {self.email}>"


class EmailChange(Base, ModelMixin):
    """Used when user wants to update their email"""

    __tablename__ = "email_change"

    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"),
        nullable=False,
        unique=True,
        index=True,
    )
    new_email = sa.Column(sa.String(256), unique=True, nullable=False)
    code = sa.Column(sa.String(128), unique=True, nullable=False)
    expired = sa.Column(ArrowType, nullable=False, default=_expiration_12h)

    user = orm.relationship(User)

    def is_expired(self):
        return self.expired < arrow.now()

    def __repr__(self):
        return f"<EmailChange {self.id} {self.new_email} {self.user_id}>"


class AliasUsedOn(Base, ModelMixin):
    """Used to know where an alias is created"""

    __tablename__ = "alias_used_on"

    __table_args__ = (
        sa.UniqueConstraint("alias_id", "hostname", name="uq_alias_used"),
    )

    alias_id = sa.Column(sa.ForeignKey(Alias.id, ondelete="cascade"), nullable=False)
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    alias = orm.relationship(Alias)

    hostname = sa.Column(sa.String(1024), nullable=False)


class ApiKey(Base, ModelMixin):
    """used in browser extension to identify user"""

    __tablename__ = "api_key"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    code = sa.Column(sa.String(128), unique=True, nullable=False)
    name = sa.Column(sa.String(128), nullable=True)
    last_used = sa.Column(ArrowType, default=None)
    times = sa.Column(sa.Integer, default=0, nullable=False)
    sudo_mode_at = sa.Column(ArrowType, default=None)

    user = orm.relationship(User)

    @classmethod
    def create(cls, user_id, name=None, **kwargs):
        code = random_string(60)
        if cls.get_by(code=code):
            code = str(uuid.uuid4())

        return super().create(user_id=user_id, name=name, code=code, **kwargs)

    @classmethod
    def delete_all(cls, user_id):
        Session.query(cls).filter(cls.user_id == user_id).delete()


class CustomDomain(Base, ModelMixin):
    __tablename__ = "custom_domain"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    domain = sa.Column(sa.String(128), unique=True, nullable=False)

    # default name to use when user replies/sends from alias
    name = sa.Column(sa.String(128), nullable=True, default=None)

    # mx verified
    verified = sa.Column(sa.Boolean, nullable=False, default=False)
    dkim_verified = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )
    spf_verified = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )
    dmarc_verified = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    _mailboxes = orm.relationship("Mailbox", secondary="domain_mailbox", lazy="joined")

    # an alias is created automatically the first time it receives an email
    catch_all = sa.Column(sa.Boolean, nullable=False, default=False, server_default="0")

    # option to generate random prefix version automatically
    random_prefix_generation = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # incremented when a check is failed on the domain
    # alert when the number exceeds a threshold
    # used in check_custom_domain()
    nb_failed_checks = sa.Column(
        sa.Integer, default=0, server_default="0", nullable=False
    )

    # only domain has the ownership verified can go the next DNS step
    # MX verified domains before this change don't have to do the TXT check
    # and therefore have ownership_verified=True
    ownership_verified = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # randomly generated TXT value for verifying domain ownership
    # the TXT record should be sl-verification=txt_token
    ownership_txt_token = sa.Column(sa.String(128), nullable=True)

    # if the domain is SimpleLogin subdomain, no need for the ownership, SPF, DKIM, DMARC check
    is_sl_subdomain = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    __table_args__ = (
        Index(
            "ix_unique_domain",  # Index name
            "domain",  # Columns which are part of the index
            unique=True,
            postgresql_where=Column("ownership_verified"),
        ),  # The condition
    )

    user = orm.relationship(User, foreign_keys=[user_id], backref="custom_domains")

    @property
    def mailboxes(self):
        if self._mailboxes:
            return self._mailboxes
        else:
            return [self.user.default_mailbox]

    def nb_alias(self):
        return Alias.filter_by(custom_domain_id=self.id).count()

    def get_trash_url(self):
        return config.URL + f"/dashboard/domains/{self.id}/trash"

    def get_ownership_dns_txt_value(self):
        return f"sl-verification={self.ownership_txt_token}"

    @classmethod
    def create(cls, **kwargs):
        domain = kwargs.get("domain")
        if DeletedSubdomain.get_by(domain=domain):
            raise SubdomainInTrashError

        domain: CustomDomain = super(CustomDomain, cls).create(**kwargs)

        # generate a domain ownership txt token
        if not domain.ownership_txt_token:
            domain.ownership_txt_token = random_string(30)
            Session.commit()

        if domain.is_sl_subdomain:
            user = domain.user
            user._subdomain_quota -= 1
            Session.flush()

        return domain

    @classmethod
    def delete(cls, obj_id):
        obj: CustomDomain = cls.get(obj_id)
        if obj.is_sl_subdomain:
            DeletedSubdomain.create(domain=obj.domain)

        return super(CustomDomain, cls).delete(obj_id)

    @property
    def auto_create_rules(self):
        return sorted(self._auto_create_rules, key=lambda rule: rule.order)

    def __repr__(self):
        return f"<Custom Domain {self.domain}>"


class AutoCreateRule(Base, ModelMixin):
    """Alias auto creation rule for custom domain"""

    __tablename__ = "auto_create_rule"

    __table_args__ = (
        sa.UniqueConstraint(
            "custom_domain_id", "order", name="uq_auto_create_rule_order"
        ),
    )

    custom_domain_id = sa.Column(
        sa.ForeignKey(CustomDomain.id, ondelete="cascade"), nullable=False
    )
    # an alias is auto created if it matches the regex
    regex = sa.Column(sa.String(512), nullable=False)

    # the order in which rules are evaluated in case there are multiple rules
    order = sa.Column(sa.Integer, default=0, nullable=False)

    custom_domain = orm.relationship(CustomDomain, backref="_auto_create_rules")

    mailboxes = orm.relationship(
        "Mailbox", secondary="auto_create_rule__mailbox", lazy="joined"
    )


class AutoCreateRuleMailbox(Base, ModelMixin):
    """store auto create rule - mailbox association"""

    __tablename__ = "auto_create_rule__mailbox"
    __table_args__ = (
        sa.UniqueConstraint(
            "auto_create_rule_id", "mailbox_id", name="uq_auto_create_rule_mailbox"
        ),
    )

    auto_create_rule_id = sa.Column(
        sa.ForeignKey(AutoCreateRule.id, ondelete="cascade"), nullable=False
    )
    mailbox_id = sa.Column(
        sa.ForeignKey("mailbox.id", ondelete="cascade"), nullable=False
    )


class DomainDeletedAlias(Base, ModelMixin):
    """Store all deleted alias for a domain"""

    __tablename__ = "domain_deleted_alias"

    __table_args__ = (
        sa.UniqueConstraint("domain_id", "email", name="uq_domain_trash"),
    )

    email = sa.Column(sa.String(256), nullable=False)
    domain_id = sa.Column(
        sa.ForeignKey("custom_domain.id", ondelete="cascade"), nullable=False
    )
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    domain = orm.relationship(CustomDomain)
    user = orm.relationship(User, foreign_keys=[user_id])

    @classmethod
    def create(cls, **kw):
        raise Exception("should use delete_alias(alias,user) instead")

    def __repr__(self):
        return f"<DomainDeletedAlias {self.id} {self.email}>"


class LifetimeCoupon(Base, ModelMixin):
    __tablename__ = "lifetime_coupon"

    code = sa.Column(sa.String(128), nullable=False, unique=True)
    nb_used = sa.Column(sa.Integer, nullable=False)
    paid = sa.Column(sa.Boolean, default=False, server_default="0", nullable=False)
    comment = sa.Column(sa.Text, nullable=True)


class Coupon(Base, ModelMixin):
    __tablename__ = "coupon"

    code = sa.Column(sa.String(128), nullable=False, unique=True)

    # by default a coupon is for 1 year
    nb_year = sa.Column(sa.Integer, nullable=False, server_default="1", default=1)

    # whether the coupon has been used
    used = sa.Column(sa.Boolean, default=False, server_default="0", nullable=False)

    # the user who uses the code
    # non-null when the coupon is used
    used_by_user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=True
    )

    is_giveaway = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    comment = sa.Column(sa.Text, nullable=True)

    # a coupon can have an expiration
    expires_date = sa.Column(ArrowType, nullable=True)


class Directory(Base, ModelMixin):
    __tablename__ = "directory"
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    name = sa.Column(sa.String(128), unique=True, nullable=False)
    # when a directory is disabled, new alias can't be created on the fly
    disabled = sa.Column(sa.Boolean, default=False, nullable=False, server_default="0")

    user = orm.relationship(User, backref="directories")

    _mailboxes = orm.relationship(
        "Mailbox", secondary="directory_mailbox", lazy="joined"
    )

    @property
    def mailboxes(self):
        if self._mailboxes:
            return self._mailboxes
        else:
            return [self.user.default_mailbox]

    def nb_alias(self):
        return Alias.filter_by(directory_id=self.id).count()

    @classmethod
    def create(cls, *args, **kwargs):
        name = kwargs.get("name")
        if DeletedDirectory.get_by(name=name):
            raise DirectoryInTrashError

        directory = super(Directory, cls).create(*args, **kwargs)
        Session.flush()

        user = directory.user
        user._directory_quota -= 1

        Session.flush()
        return directory

    @classmethod
    def delete(cls, obj_id):
        obj: Directory = cls.get(obj_id)
        user = obj.user
        # Put all aliases belonging to this directory to global or domain trash
        for alias in Alias.filter_by(directory_id=obj_id):
            from app import alias_utils

            alias_utils.delete_alias(alias, user)

        DeletedDirectory.create(name=obj.name)
        cls.filter(cls.id == obj_id).delete()

        Session.commit()

    def __repr__(self):
        return f"<Directory {self.name}>"


class Job(Base, ModelMixin):
    """Used to schedule one-time job in the future"""

    __tablename__ = "job"

    name = sa.Column(sa.String(128), nullable=False)
    payload = sa.Column(sa.JSON)

    # whether the job has been taken by the job runner
    taken = sa.Column(sa.Boolean, default=False, nullable=False)
    run_at = sa.Column(ArrowType)
    state = sa.Column(
        sa.Integer,
        nullable=False,
        server_default=str(JobState.ready.value),
        default=JobState.ready.value,
    )
    attempts = sa.Column(sa.Integer, nullable=False, server_default="0", default=0)
    taken_at = sa.Column(ArrowType, nullable=True)

    def __repr__(self):
        return f"<Job {self.id} {self.name} {self.payload}>"


class Mailbox(Base, ModelMixin):
    __tablename__ = "mailbox"
    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, index=True
    )
    email = sa.Column(sa.String(256), nullable=False, index=True)
    verified = sa.Column(sa.Boolean, default=False, nullable=False)
    force_spf = sa.Column(sa.Boolean, default=True, server_default="1", nullable=False)

    # used when user wants to update mailbox email
    new_email = sa.Column(sa.String(256), unique=True)

    pgp_public_key = sa.Column(sa.Text, nullable=True)
    pgp_finger_print = sa.Column(sa.String(512), nullable=True)
    disable_pgp = sa.Column(
        sa.Boolean, default=False, nullable=False, server_default="0"
    )

    # incremented when a check is failed on the mailbox
    # alert when the number exceeds a threshold
    # used in sanity_check()
    nb_failed_checks = sa.Column(
        sa.Integer, default=0, server_default="0", nullable=False
    )

    # a mailbox can be disabled if it can't be reached
    disabled = sa.Column(sa.Boolean, default=False, nullable=False, server_default="0")

    generic_subject = sa.Column(sa.String(78), nullable=True)

    __table_args__ = (sa.UniqueConstraint("user_id", "email", name="uq_mailbox_user"),)

    user = orm.relationship(User, foreign_keys=[user_id])

    def pgp_enabled(self) -> bool:
        if self.pgp_finger_print and not self.disable_pgp:
            return True

        return False

    def nb_alias(self):
        return (
            AliasMailbox.filter_by(mailbox_id=self.id).count()
            + Alias.filter_by(mailbox_id=self.id).count()
        )

    @classmethod
    def delete(cls, obj_id):
        mailbox: Mailbox = cls.get(obj_id)
        user = mailbox.user

        # Put all aliases belonging to this mailbox to global or domain trash
        for alias in Alias.filter_by(mailbox_id=obj_id):
            # special handling for alias that has several mailboxes and has mailbox_id=obj_id
            if len(alias.mailboxes) > 1:
                # use the first mailbox found in alias._mailboxes
                first_mb = alias._mailboxes[0]
                alias.mailbox_id = first_mb.id
                alias._mailboxes.remove(first_mb)
            else:
                from app import alias_utils

                # only put aliases that have mailbox as a single mailbox into trash
                alias_utils.delete_alias(alias, user)
            Session.commit()

        cls.filter(cls.id == obj_id).delete()
        Session.commit()

    @property
    def aliases(self) -> [Alias]:
        ret = Alias.filter_by(mailbox_id=self.id).all()

        for am in AliasMailbox.filter_by(mailbox_id=self.id):
            ret.append(am.alias)

        return ret

    def __repr__(self):
        return f"<Mailbox {self.id} {self.email}>"


class AccountActivation(Base, ModelMixin):
    """contains code to activate the user account when they sign up on mobile"""

    __tablename__ = "account_activation"

    user_id = sa.Column(
        sa.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )
    # the activation code is usually 6 digits
    code = sa.Column(sa.String(10), nullable=False)

    # nb tries decrements each time user enters wrong code
    tries = sa.Column(sa.Integer, default=3, nullable=False)

    __table_args__ = (
        CheckConstraint(tries >= 0, name="account_activation_tries_positive"),
        {},
    )


class RefusedEmail(Base, ModelMixin):
    """Store emails that have been refused, i.e. bounced or classified as spams"""

    __tablename__ = "refused_email"

    # Store the full report, including logs from Sending & Receiving MTA
    full_report_path = sa.Column(sa.String(128), unique=True, nullable=False)

    # The original email, to display to user
    path = sa.Column(sa.String(128), unique=True, nullable=True)

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    # the email content will be deleted at this date
    delete_at = sa.Column(ArrowType, nullable=False, default=_expiration_7d)

    # toggle this when email content (stored at full_report_path & path are deleted)
    deleted = sa.Column(sa.Boolean, nullable=False, default=False, server_default="0")

    def get_url(self, expires_in=3600):
        if self.path:
            return s3.get_url(self.path, expires_in)
        else:
            return s3.get_url(self.full_report_path, expires_in)

    def __repr__(self):
        return f"<Refused Email {self.id} {self.path} {self.delete_at}>"


class Referral(Base, ModelMixin):
    """Referral code so user can invite others"""

    __tablename__ = "referral"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    name = sa.Column(sa.String(512), nullable=True, default=None)

    code = sa.Column(sa.String(128), unique=True, nullable=False)

    user = orm.relationship(User, foreign_keys=[user_id], backref="referrals")

    @property
    def nb_user(self) -> int:
        return User.filter_by(referral_id=self.id, activated=True).count()

    @property
    def nb_paid_user(self) -> int:
        res = 0
        for user in User.filter_by(referral_id=self.id, activated=True):
            if user.is_paid():
                res += 1

        return res

    def link(self):
        return f"{config.LANDING_PAGE_URL}?slref={self.code}"

    def __repr__(self):
        return f"<Referral {self.code}>"


class SentAlert(Base, ModelMixin):
    """keep track of alerts sent to user.
    User can receive an alert when there's abnormal activity on their aliases such as
    - reverse-alias not used by the owning mailbox
    - SPF fails when using the reverse-alias
    - bounced email
    - ...

    Different rate controls can then be implemented based on SentAlert:
    - only once alert: an alert type should be sent only once
    - max number of sent per 24H: an alert type should not be sent more than X times in 24h
    """

    __tablename__ = "sent_alert"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    to_email = sa.Column(sa.String(256), nullable=False)
    alert_type = sa.Column(sa.String(256), nullable=False)


class AliasMailbox(Base, ModelMixin):
    __tablename__ = "alias_mailbox"
    __table_args__ = (
        sa.UniqueConstraint("alias_id", "mailbox_id", name="uq_alias_mailbox"),
    )

    alias_id = sa.Column(
        sa.ForeignKey(Alias.id, ondelete="cascade"), nullable=False, index=True
    )
    mailbox_id = sa.Column(
        sa.ForeignKey(Mailbox.id, ondelete="cascade"), nullable=False, index=True
    )

    alias = orm.relationship(Alias)


class AliasHibp(Base, ModelMixin):
    __tablename__ = "alias_hibp"

    __table_args__ = (sa.UniqueConstraint("alias_id", "hibp_id", name="uq_alias_hibp"),)

    alias_id = sa.Column(
        sa.Integer(), sa.ForeignKey("alias.id", ondelete="cascade"), index=True
    )
    hibp_id = sa.Column(
        sa.Integer(), sa.ForeignKey("hibp.id", ondelete="cascade"), index=True
    )

    alias = orm.relationship(
        "Alias", backref=orm.backref("alias_hibp", cascade="all, delete-orphan")
    )
    hibp = orm.relationship(
        "Hibp", backref=orm.backref("alias_hibp", cascade="all, delete-orphan")
    )


class DirectoryMailbox(Base, ModelMixin):
    __tablename__ = "directory_mailbox"
    __table_args__ = (
        sa.UniqueConstraint("directory_id", "mailbox_id", name="uq_directory_mailbox"),
    )

    directory_id = sa.Column(
        sa.ForeignKey(Directory.id, ondelete="cascade"), nullable=False
    )
    mailbox_id = sa.Column(
        sa.ForeignKey(Mailbox.id, ondelete="cascade"), nullable=False
    )


class DomainMailbox(Base, ModelMixin):
    """store the owning mailboxes for a domain"""

    __tablename__ = "domain_mailbox"

    __table_args__ = (
        sa.UniqueConstraint("domain_id", "mailbox_id", name="uq_domain_mailbox"),
    )

    domain_id = sa.Column(
        sa.ForeignKey(CustomDomain.id, ondelete="cascade"), nullable=False
    )
    mailbox_id = sa.Column(
        sa.ForeignKey(Mailbox.id, ondelete="cascade"), nullable=False
    )


_NB_RECOVERY_CODE = 8
_RECOVERY_CODE_LENGTH = 8


class RecoveryCode(Base, ModelMixin):
    """allow user to login in case you lose any of your authenticators"""

    __tablename__ = "recovery_code"
    __table_args__ = (sa.UniqueConstraint("user_id", "code", name="uq_recovery_code"),)

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    code = sa.Column(sa.String(64), nullable=False)
    used = sa.Column(sa.Boolean, nullable=False, default=False)
    used_at = sa.Column(ArrowType, nullable=True, default=None)

    user = orm.relationship(User)

    @classmethod
    def _hash_code(cls, code: str) -> str:
        code_hmac = hmac.new(
            config.RECOVERY_CODE_HMAC_SECRET.encode("utf-8"),
            code.encode("utf-8"),
            "sha3_224",
        )
        return base64.urlsafe_b64encode(code_hmac.digest()).decode("utf-8").rstrip("=")

    @classmethod
    def generate(cls, user):
        """generate recovery codes for user"""
        # delete all existing codes
        cls.filter_by(user_id=user.id).delete()
        Session.flush()

        nb_code = 0
        raw_codes = []
        while nb_code < _NB_RECOVERY_CODE:
            raw_code = random_string(_RECOVERY_CODE_LENGTH)
            encoded_code = cls._hash_code(raw_code)
            if not cls.get_by(user_id=user.id, code=encoded_code):
                cls.create(user_id=user.id, code=encoded_code)
                raw_codes.append(raw_code)
                nb_code += 1

        LOG.d("Create recovery codes for %s", user)
        Session.commit()
        return raw_codes

    @classmethod
    def find_by_user_code(cls, user: User, code: str):
        hashed_code = cls._hash_code(code)
        # TODO: Only return hashed codes once there aren't unhashed codes in the db.
        found_code = cls.get_by(user_id=user.id, code=hashed_code)
        if found_code:
            return found_code
        return cls.get_by(user_id=user.id, code=code)

    @classmethod
    def empty(cls, user):
        """Delete all recovery codes for user"""
        cls.filter_by(user_id=user.id).delete()
        Session.commit()


class Notification(Base, ModelMixin):
    __tablename__ = "notification"
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    message = sa.Column(sa.Text, nullable=False)
    title = sa.Column(sa.String(512))

    # whether user has marked the notification as read
    read = sa.Column(sa.Boolean, nullable=False, default=False)

    @staticmethod
    def render(template_name, **kwargs) -> str:
        templates_dir = os.path.join(config.ROOT_DIR, "templates")
        env = Environment(loader=FileSystemLoader(templates_dir))

        template = env.get_template(template_name)

        return template.render(
            URL=config.URL,
            LANDING_PAGE_URL=config.LANDING_PAGE_URL,
            YEAR=arrow.now().year,
            **kwargs,
        )


class SLDomain(Base, ModelMixin):
    """SimpleLogin domains"""

    __tablename__ = "public_domain"

    domain = sa.Column(sa.String(128), unique=True, nullable=False)

    # only available for premium accounts
    premium_only = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # if True, the domain can be used for the subdomain feature
    can_use_subdomain = sa.Column(
        sa.Boolean, nullable=False, default=False, server_default="0"
    )

    # if enabled, do not show this domain when user creates a custom alias
    hidden = sa.Column(sa.Boolean, nullable=False, default=False, server_default="0")

    # the order in which the domains are shown when user creates a custom alias
    order = sa.Column(sa.Integer, nullable=False, default=0, server_default="0")

    def __repr__(self):
        return f"<SLDomain {self.domain} {'Premium' if self.premium_only else 'Free'}"


class Monitoring(Base, ModelMixin):
    """
    Store different host information over the time in order to
    - alert issues in (almost) real time
    - analyze data trending
    """

    __tablename__ = "monitoring"

    host = sa.Column(sa.String(256), nullable=False)

    # Postfix stats
    incoming_queue = sa.Column(sa.Integer, nullable=False)
    active_queue = sa.Column(sa.Integer, nullable=False)
    deferred_queue = sa.Column(sa.Integer, nullable=False)


class BatchImport(Base, ModelMixin):
    __tablename__ = "batch_import"
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    file_id = sa.Column(sa.ForeignKey(File.id, ondelete="cascade"), nullable=False)
    processed = sa.Column(sa.Boolean, nullable=False, default=False)
    summary = sa.Column(sa.Text, nullable=True, default=None)

    file = orm.relationship(File)
    user = orm.relationship(User)

    def nb_alias(self):
        return Alias.filter_by(batch_import_id=self.id).count()

    def __repr__(self):
        return f"<BatchImport {self.id}>"


class AuthorizedAddress(Base, ModelMixin):
    """Authorize other addresses to send emails from aliases that are owned by a mailbox"""

    __tablename__ = "authorized_address"

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    mailbox_id = sa.Column(
        sa.ForeignKey(Mailbox.id, ondelete="cascade"), nullable=False
    )
    email = sa.Column(sa.String(256), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("mailbox_id", "email", name="uq_authorize_address"),
    )

    mailbox = orm.relationship(Mailbox, backref="authorized_addresses")

    def __repr__(self):
        return f"<AuthorizedAddress {self.id} {self.email} {self.mailbox_id}>"


class Metric2(Base, ModelMixin):
    """
    For storing different metrics like number of users, etc
    Store each metric as a column as opposed to having different rows as in Metric
    """

    __tablename__ = "metric2"
    date = sa.Column(ArrowType, default=arrow.utcnow, nullable=False)

    nb_user = sa.Column(sa.Float, nullable=True)
    nb_activated_user = sa.Column(sa.Float, nullable=True)
    nb_proton_user = sa.Column(sa.Float, nullable=True)

    nb_premium = sa.Column(sa.Float, nullable=True)
    nb_apple_premium = sa.Column(sa.Float, nullable=True)
    nb_cancelled_premium = sa.Column(sa.Float, nullable=True)
    nb_manual_premium = sa.Column(sa.Float, nullable=True)
    nb_coinbase_premium = sa.Column(sa.Float, nullable=True)
    nb_proton_premium = sa.Column(sa.Float, nullable=True)

    # nb users who have been referred
    nb_referred_user = sa.Column(sa.Float, nullable=True)
    nb_referred_user_paid = sa.Column(sa.Float, nullable=True)

    nb_alias = sa.Column(sa.Float, nullable=True)

    # Obsolete as only for the last 14 days
    nb_forward = sa.Column(sa.Float, nullable=True)
    nb_block = sa.Column(sa.Float, nullable=True)
    nb_reply = sa.Column(sa.Float, nullable=True)
    nb_bounced = sa.Column(sa.Float, nullable=True)
    nb_spam = sa.Column(sa.Float, nullable=True)

    # should be used instead
    nb_forward_last_24h = sa.Column(sa.Float, nullable=True)
    nb_block_last_24h = sa.Column(sa.Float, nullable=True)
    nb_reply_last_24h = sa.Column(sa.Float, nullable=True)
    nb_bounced_last_24h = sa.Column(sa.Float, nullable=True)
    # includes bounces for both forwarding and transactional email
    nb_total_bounced_last_24h = sa.Column(sa.Float, nullable=True)

    nb_verified_custom_domain = sa.Column(sa.Float, nullable=True)
    nb_subdomain = sa.Column(sa.Float, nullable=True)
    nb_directory = sa.Column(sa.Float, nullable=True)

    nb_deleted_directory = sa.Column(sa.Float, nullable=True)
    nb_deleted_subdomain = sa.Column(sa.Float, nullable=True)

    nb_app = sa.Column(sa.Float, nullable=True)


class DailyMetric(Base, ModelMixin):
    """
    For storing daily event-based metrics.
    The difference between DailyEventMetric and Metric2 is Metric2 stores the total
    whereas DailyEventMetric is reset for a new day
    """

    __tablename__ = "daily_metric"
    date = sa.Column(sa.Date, nullable=False, unique=True)

    # users who sign up via web without using "Login with Proton"
    nb_new_web_non_proton_user = sa.Column(
        sa.Integer, nullable=False, server_default="0", default=0
    )

    nb_alias = sa.Column(sa.Integer, nullable=False, server_default="0", default=0)

    @staticmethod
    def get_or_create_today_metric() -> DailyMetric:
        today = arrow.utcnow().date()
        daily_metric = DailyMetric.get_by(date=today)
        if not daily_metric:
            daily_metric = DailyMetric.create(
                date=today, nb_new_web_non_proton_user=0, nb_alias=0
            )
        return daily_metric


class Bounce(Base, ModelMixin):
    """Record all bounces. Deleted after 7 days"""

    __tablename__ = "bounce"
    email = sa.Column(sa.String(256), nullable=False, index=True)
    info = sa.Column(sa.Text, nullable=True)


class TransactionalEmail(Base, ModelMixin):
    """Storing all email addresses that receive transactional emails, including account email and mailboxes.
    Deleted after 7 days
    """

    __tablename__ = "transactional_email"
    email = sa.Column(sa.String(256), nullable=False, unique=False)


class Payout(Base, ModelMixin):
    """Referral payouts"""

    __tablename__ = "payout"
    user_id = sa.Column(sa.ForeignKey("users.id", ondelete="cascade"), nullable=False)

    # in USD
    amount = sa.Column(sa.Float, nullable=False)

    # BTC, PayPal, etc
    payment_method = sa.Column(sa.String(256), nullable=False)

    # number of upgraded user included in this payout
    number_upgraded_account = sa.Column(sa.Integer, nullable=False)

    comment = sa.Column(sa.Text)

    user = orm.relationship(User)


class IgnoredEmail(Base, ModelMixin):
    """If an email has mail_from and rcpt_to present in this table, discard it by returning 250 status."""

    __tablename__ = "ignored_email"

    mail_from = sa.Column(sa.String(512), nullable=False)
    rcpt_to = sa.Column(sa.String(512), nullable=False)


class IgnoreBounceSender(Base, ModelMixin):
    """Ignore sender that doesn't correctly handle bounces, for example noreply@github.com"""

    __tablename__ = "ignore_bounce_sender"

    mail_from = sa.Column(sa.String(512), nullable=False, unique=True)

    def __repr__(self):
        return f"<NoReplySender {self.mail_from}"


class MessageIDMatching(Base, ModelMixin):
    """Store the SL Message ID and the original Message ID"""

    __tablename__ = "message_id_matching"

    # SimpleLogin Message ID
    sl_message_id = sa.Column(sa.String(512), unique=True, nullable=False)
    original_message_id = sa.Column(sa.String(1024), unique=True, nullable=False)

    # to track what email_log that has created this matching
    email_log_id = sa.Column(
        sa.ForeignKey("email_log.id", ondelete="cascade"), nullable=True
    )

    email_log = orm.relationship("EmailLog")


class DeletedDirectory(Base, ModelMixin):
    """To avoid directory from being reused"""

    __tablename__ = "deleted_directory"

    name = sa.Column(sa.String(128), unique=True, nullable=False)


class DeletedSubdomain(Base, ModelMixin):
    """To avoid directory from being reused"""

    __tablename__ = "deleted_subdomain"

    domain = sa.Column(sa.String(128), unique=True, nullable=False)


class InvalidMailboxDomain(Base, ModelMixin):
    """Domains that can't be used as mailbox"""

    __tablename__ = "invalid_mailbox_domain"

    domain = sa.Column(sa.String(256), unique=True, nullable=False)


# region Phone
class PhoneCountry(Base, ModelMixin):
    __tablename__ = "phone_country"

    name = sa.Column(sa.String(128), unique=True, nullable=False)


class PhoneNumber(Base, ModelMixin):
    __tablename__ = "phone_number"

    country_id = sa.Column(
        sa.ForeignKey(PhoneCountry.id, ondelete="cascade"), nullable=False
    )

    # with country code, e.g. +33612345678
    number = sa.Column(sa.String(128), unique=True, nullable=False)

    active = sa.Column(sa.Boolean, nullable=False, default=True)

    # do not load this column
    comment = deferred(sa.Column(sa.Text, nullable=True))

    country = orm.relationship(PhoneCountry)


class PhoneReservation(Base, ModelMixin):
    __tablename__ = "phone_reservation"

    number_id = sa.Column(
        sa.ForeignKey(PhoneNumber.id, ondelete="cascade"), nullable=False
    )

    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    number = orm.relationship(PhoneNumber)

    start = sa.Column(ArrowType, nullable=False)
    end = sa.Column(ArrowType, nullable=False)


class PhoneMessage(Base, ModelMixin):
    __tablename__ = "phone_message"

    number_id = sa.Column(
        sa.ForeignKey(PhoneNumber.id, ondelete="cascade"), nullable=False
    )

    from_number = sa.Column(sa.String(128), nullable=False)
    body = sa.Column(sa.Text)

    number = orm.relationship(PhoneNumber)


# endregion


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    created_at = sa.Column(ArrowType, default=arrow.utcnow, nullable=False)
    admin_user_id = sa.Column(
        sa.ForeignKey("users.id", ondelete="cascade"), nullable=False, index=True
    )
    action = sa.Column(sa.Integer, nullable=False)
    model = sa.Column(sa.Text, nullable=False)
    model_id = sa.Column(sa.Integer, nullable=True)
    data = sa.Column(sa.JSON, nullable=False)

    admin = orm.relationship(User, foreign_keys=[admin_user_id])

    @classmethod
    def create(cls, **kw):
        r = cls(**kw)
        Session.add(r)

        return r

    @classmethod
    def create_manual_upgrade(
        cls, admin_user_id: int, upgrade_type: str, user_id: int, giveaway: bool
    ):
        cls.create(
            admin_user_id=admin_user_id,
            action=AuditLogActionEnum.manual_upgrade.value,
            model="User",
            model_id=user_id,
            data={
                "upgrade_type": upgrade_type,
                "giveaway": giveaway,
            },
        )

    @classmethod
    def extend_trial(
        cls, admin_user_id: int, user_id: int, trial_end: arrow.Arrow, extend_time: str
    ):
        cls.create(
            admin_user_id=admin_user_id,
            action=AuditLogActionEnum.extend_trial.value,
            model="User",
            model_id=user_id,
            data={
                "trial_end": trial_end.format(arrow.FORMAT_RFC3339),
                "extend_time": extend_time,
            },
        )

    @classmethod
    def disable_otp_fido(
        cls, admin_user_id: int, user_id: int, had_otp: bool, had_fido: bool
    ):
        cls.create(
            admin_user_id=admin_user_id,
            action=AuditLogActionEnum.disable_2fa.value,
            model="User",
            model_id=user_id,
            data={"had_otp": had_otp, "had_fido": had_fido},
        )

    @classmethod
    def logged_as_user(cls, admin_user_id: int, user_id: int):
        cls.create(
            admin_user_id=admin_user_id,
            action=AuditLogActionEnum.logged_as_user.value,
            model="User",
            model_id=user_id,
            data={},
        )

    @classmethod
    def extend_subscription(
        cls,
        admin_user_id: int,
        user_id: int,
        subscription_end: arrow.Arrow,
        extend_time: str,
    ):
        cls.create(
            admin_user_id=admin_user_id,
            action=AuditLogActionEnum.extend_subscription.value,
            model="User",
            model_id=user_id,
            data={
                "subscription_end": subscription_end.format(arrow.FORMAT_RFC3339),
                "extend_time": extend_time,
            },
        )

    @classmethod
    def downloaded_provider_complaint(cls, admin_user_id: int, complaint_id: int):
        cls.create(
            admin_user_id=admin_user_id,
            action=AuditLogActionEnum.download_provider_complaint.value,
            model="ProviderComplaint",
            model_id=complaint_id,
            data={},
        )


class ProviderComplaintState(EnumE):
    new = 0
    reviewed = 1


class ProviderComplaint(Base, ModelMixin):
    __tablename__ = "provider_complaint"

    user_id = sa.Column(sa.ForeignKey("users.id"), nullable=False)
    state = sa.Column(
        sa.Integer, nullable=False, server_default=str(ProviderComplaintState.new.value)
    )
    phase = sa.Column(
        sa.Integer, nullable=False, server_default=str(Phase.unknown.value)
    )
    # Point to the email that has been refused
    refused_email_id = sa.Column(
        sa.ForeignKey("refused_email.id", ondelete="cascade"), nullable=True
    )

    user = orm.relationship(User, foreign_keys=[user_id])
    refused_email = orm.relationship(RefusedEmail, foreign_keys=[refused_email_id])


class Partner(Base, ModelMixin):
    __tablename__ = "partner"

    name = sa.Column(sa.String(128), unique=True, nullable=False)
    contact_email = sa.Column(sa.String(128), unique=True, nullable=False)

    @staticmethod
    def find_by_token(token: str) -> Optional[Partner]:
        hmaced = PartnerApiToken.hmac_token(token)
        res = (
            Session.query(Partner, PartnerApiToken)
            .filter(
                and_(
                    PartnerApiToken.token == hmaced,
                    Partner.id == PartnerApiToken.partner_id,
                )
            )
            .first()
        )
        if res:
            partner, partner_api_token = res
            return partner
        return None


class PartnerApiToken(Base, ModelMixin):
    __tablename__ = "partner_api_token"

    token = sa.Column(sa.String(50), unique=True, nullable=False, index=True)
    partner_id = sa.Column(
        sa.ForeignKey("partner.id", ondelete="cascade"), nullable=False, index=True
    )
    expiration_time = sa.Column(ArrowType, unique=False, nullable=True)

    @staticmethod
    def generate(
        partner_id: int, expiration_time: Optional[ArrowType]
    ) -> Tuple[PartnerApiToken, str]:
        raw_token = random_string(32)
        encoded = PartnerApiToken.hmac_token(raw_token)
        instance = PartnerApiToken.create(
            token=encoded, partner_id=partner_id, expiration_time=expiration_time
        )
        return instance, raw_token

    @staticmethod
    def hmac_token(token: str) -> str:
        as_str = base64.b64encode(
            hmac.new(
                config.PARTNER_API_TOKEN_SECRET.encode("utf-8"),
                token.encode("utf-8"),
                hashlib.sha3_256,
            ).digest()
        ).decode("utf-8")
        return as_str.rstrip("=")


class PartnerUser(Base, ModelMixin):
    __tablename__ = "partner_user"

    user_id = sa.Column(
        sa.ForeignKey("users.id", ondelete="cascade"),
        unique=True,
        nullable=False,
        index=True,
    )
    partner_id = sa.Column(
        sa.ForeignKey("partner.id", ondelete="cascade"), nullable=False, index=True
    )
    external_user_id = sa.Column(sa.String(128), unique=False, nullable=False)
    partner_email = sa.Column(sa.String(255), unique=False, nullable=True)

    user = orm.relationship(User, foreign_keys=[user_id])
    partner = orm.relationship(Partner, foreign_keys=[partner_id])

    __table_args__ = (
        sa.UniqueConstraint(
            "partner_id", "external_user_id", name="uq_partner_id_external_user_id"
        ),
    )


class PartnerSubscription(Base, ModelMixin):
    """
    For users who have a subscription via a partner
    """

    __tablename__ = "partner_subscription"

    partner_user_id = sa.Column(
        sa.ForeignKey(PartnerUser.id, ondelete="cascade"), nullable=False, unique=True
    )

    # when the partner subscription ends
    end_at = sa.Column(ArrowType, nullable=False)

    partner_user = orm.relationship(PartnerUser)

    @classmethod
    def find_by_user_id(cls, user_id: int) -> Optional[PartnerSubscription]:
        res = (
            Session.query(PartnerSubscription, PartnerUser)
            .filter(
                and_(
                    PartnerUser.user_id == user_id,
                    PartnerSubscription.partner_user_id == PartnerUser.id,
                )
            )
            .first()
        )
        if res:
            subscription, partner_user = res
            return subscription
        return None

    def is_active(self):
        return self.end_at > arrow.now().shift(days=-_PARTNER_SUBSCRIPTION_GRACE_DAYS)


# endregion


class Newsletter(Base, ModelMixin):
    __tablename__ = "newsletter"
    subject = sa.Column(sa.String(), nullable=False, unique=True, index=True)

    html = sa.Column(sa.Text)
    plain_text = sa.Column(sa.Text)

    def __repr__(self):
        return f"<Newsletter {self.id} {self.subject}>"


class NewsletterUser(Base, ModelMixin):
    """This model keeps track of what newsletter is sent to what user"""

    __tablename__ = "newsletter_user"
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=True)
    newsletter_id = sa.Column(
        sa.ForeignKey(Newsletter.id, ondelete="cascade"), nullable=True
    )
    # not use created_at here as it should only used for auditting purpose
    sent_at = sa.Column(ArrowType, default=arrow.utcnow, nullable=False)

    user = orm.relationship(User)
    newsletter = orm.relationship(Newsletter)


class ApiToCookieToken(Base, ModelMixin):
    __tablename__ = "api_cookie_token"
    code = sa.Column(sa.String(128), unique=True, nullable=False)
    user_id = sa.Column(sa.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    api_key_id = sa.Column(sa.ForeignKey(ApiKey.id, ondelete="cascade"), nullable=False)

    user = orm.relationship(User)
    api_key = orm.relationship(ApiKey)

    @classmethod
    def create(cls, **kwargs):
        code = secrets.token_urlsafe(32)

        return super().create(code=code, **kwargs)
