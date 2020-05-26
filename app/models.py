import enum
import random
import uuid
from email.utils import formataddr
from typing import List

import arrow
import bcrypt
from flask import url_for
from flask_login import UserMixin
from sqlalchemy import text, desc, CheckConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy_utils import ArrowType

from app import s3
from app.config import (
    EMAIL_DOMAIN,
    MAX_NB_EMAIL_FREE_PLAN,
    URL,
    AVATAR_URL_EXPIRATION,
    JOB_ONBOARDING_1,
    JOB_ONBOARDING_2,
    JOB_ONBOARDING_3,
    JOB_ONBOARDING_4,
    LANDING_PAGE_URL,
    FIRST_ALIAS_DOMAIN,
    DISABLE_ONBOARDING,
    PAGE_LIMIT,
)
from app.errors import AliasInTrashError
from app.extensions import db
from app.log import LOG
from app.oauth_models import Scope
from app.utils import convert_to_id, random_string, random_words, random_word


class ModelMixin(object):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    created_at = db.Column(ArrowType, default=arrow.utcnow, nullable=False)
    updated_at = db.Column(ArrowType, default=None, onupdate=arrow.utcnow)

    _repr_hide = ["created_at", "updated_at"]

    @classmethod
    def query(cls):
        return db.session.query(cls)

    @classmethod
    def get(cls, id):
        return cls.query.get(id)

    @classmethod
    def get_by(cls, **kw):
        return cls.query.filter_by(**kw).first()

    @classmethod
    def filter_by(cls, **kw):
        return cls.query.filter_by(**kw)

    @classmethod
    def get_or_create(cls, **kw):
        r = cls.get_by(**kw)
        if not r:
            r = cls(**kw)
            db.session.add(r)

        return r

    @classmethod
    def create(cls, **kw):
        r = cls(**kw)
        db.session.add(r)
        return r

    def save(self):
        db.session.add(self)

    @classmethod
    def delete(cls, obj_id):
        cls.query.filter(cls.id == obj_id).delete()

    def __repr__(self):
        values = ", ".join(
            "%s=%r" % (n, getattr(self, n))
            for n in self.__table__.c.keys()
            if n not in self._repr_hide
        )
        return "%s(%s)" % (self.__class__.__name__, values)


class File(db.Model, ModelMixin):
    path = db.Column(db.String(128), unique=True, nullable=False)
    user_id = db.Column(db.ForeignKey("users.id", ondelete="cascade"), nullable=True)

    def get_url(self, expires_in=3600):
        return s3.get_url(self.path, expires_in)


class EnumE(enum.Enum):
    @classmethod
    def has_value(cls, value: int) -> bool:
        return value in set(item.value for item in cls)


class PlanEnum(EnumE):
    monthly = 2
    yearly = 3


# Specify the format for sender address
class SenderFormatEnum(EnumE):
    AT = 0  # John Wick - john at wick.com
    VIA = 1  # john@wick.com via SimpleLogin
    A = 2  # John Wick - john(a)wick.com
    FULL = 3  # John Wick - john@wick.com


class AliasGeneratorEnum(EnumE):
    word = 1  # aliases are generated based on random words
    uuid = 2  # aliases are generated based on uuid


class Fido(db.Model, ModelMixin):
    __tablename__ = "fido"
    credential_id = db.Column(db.String(), nullable=False, unique=True, index=True)
    uuid = db.Column(
        db.ForeignKey("users.fido_uuid", ondelete="cascade"),
        unique=False,
        nullable=False,
    )
    public_key = db.Column(db.String(), nullable=False, unique=True)
    sign_count = db.Column(db.Integer(), nullable=False)
    name = db.Column(db.String(128), nullable=False, unique=False)


class User(db.Model, ModelMixin, UserMixin):
    __tablename__ = "users"
    email = db.Column(db.String(256), unique=True, nullable=False)

    salt = db.Column(db.String(128), nullable=True)
    password = db.Column(db.String(128), nullable=True)

    name = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    alias_generator = db.Column(
        db.Integer,
        nullable=False,
        default=AliasGeneratorEnum.word.value,
        server_default=str(AliasGeneratorEnum.word.value),
    )
    notification = db.Column(
        db.Boolean, default=True, nullable=False, server_default="1"
    )

    activated = db.Column(db.Boolean, default=False, nullable=False)

    profile_picture_id = db.Column(db.ForeignKey(File.id), nullable=True)

    otp_secret = db.Column(db.String(16), nullable=True)
    enable_otp = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )
    last_otp = db.Column(db.String(12), nullable=True, default=False)

    # Fields for WebAuthn
    fido_uuid = db.Column(db.String(), nullable=True, unique=True)

    # whether user can use Fido
    can_use_fido = db.Column(
        db.Boolean, default=False, nullable=False, server_default="0"
    )

    def fido_enabled(self) -> bool:
        if self.can_use_fido and self.fido_uuid is not None:
            return True
        return False

    def two_factor_authentication_enabled(self) -> bool:
        return self.enable_otp or self.fido_enabled()

    # some users could have lifetime premium
    lifetime = db.Column(db.Boolean, default=False, nullable=False, server_default="0")
    paid_lifetime = db.Column(
        db.Boolean, default=False, nullable=False, server_default="0"
    )

    # user can use all premium features until this date
    trial_end = db.Column(
        ArrowType, default=lambda: arrow.now().shift(days=7, hours=1), nullable=True
    )

    # the mailbox used when create random alias
    # this field is nullable but in practice, it's always set
    # it cannot be set to non-nullable though
    # as this will create foreign key cycle between User and Mailbox
    default_mailbox_id = db.Column(
        db.ForeignKey("mailbox.id"), nullable=True, default=None
    )

    profile_picture = db.relationship(File, foreign_keys=[profile_picture_id])

    # Specify the format for sender address
    # John Wick - john at wick.com  -> 0
    # john@wick.com via SimpleLogin -> 1
    # John Wick - john@wick.com     -> 2
    # John Wick - john@wick.com     -> 3
    sender_format = db.Column(
        db.Integer, default="1", nullable=False, server_default="1"
    )

    replace_reverse_alias = db.Column(
        db.Boolean, default=False, nullable=False, server_default="0"
    )

    referral_id = db.Column(
        db.ForeignKey("referral.id", ondelete="SET NULL"), nullable=True, default=None
    )

    referral = db.relationship("Referral", foreign_keys=[referral_id])

    # whether intro has been shown to user
    intro_shown = db.Column(
        db.Boolean, default=False, nullable=False, server_default="0"
    )

    default_mailbox = db.relationship("Mailbox", foreign_keys=[default_mailbox_id])

    @classmethod
    def create(cls, email, name, password=None, **kwargs):
        user: User = super(User, cls).create(email=email, name=name, **kwargs)

        if password:
            user.set_password(password)

        db.session.flush()

        mb = Mailbox.create(user_id=user.id, email=user.email, verified=True)
        db.session.flush()
        user.default_mailbox_id = mb.id

        # create a first alias mail to show user how to use when they login
        Alias.create_new(user, prefix="my-first-alias", mailbox_id=mb.id)
        db.session.flush()

        if DISABLE_ONBOARDING:
            LOG.d("Disable onboarding emails")
            return user

        # Schedule onboarding emails
        Job.create(
            name=JOB_ONBOARDING_1,
            payload={"user_id": user.id},
            run_at=arrow.now().shift(days=1),
        )
        Job.create(
            name=JOB_ONBOARDING_2,
            payload={"user_id": user.id},
            run_at=arrow.now().shift(days=2),
        )
        Job.create(
            name=JOB_ONBOARDING_3,
            payload={"user_id": user.id},
            run_at=arrow.now().shift(days=3),
        )
        Job.create(
            name=JOB_ONBOARDING_4,
            payload={"user_id": user.id},
            run_at=arrow.now().shift(days=4),
        )
        db.session.flush()

        return user

    def _lifetime_or_active_subscription(self) -> bool:
        """True if user has lifetime licence or active subscription"""
        if self.lifetime:
            return True

        sub: Subscription = self.get_subscription()
        if sub:
            return True

        apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=self.id)
        if apple_sub and apple_sub.is_valid():
            return True

        manual_sub: ManualSubscription = ManualSubscription.get_by(user_id=self.id)
        if manual_sub and manual_sub.end_at > arrow.now():
            return True

        return False

    def in_trial(self):
        """return True if user does not have lifetime licence or an active subscription AND is in trial period"""
        if self._lifetime_or_active_subscription():
            return False

        if self.trial_end and arrow.now() < self.trial_end:
            return True

        return False

    def should_show_upgrade_button(self):
        if self._lifetime_or_active_subscription():
            # user who has canceled can also re-subscribe
            sub: Subscription = self.get_subscription()
            if sub and sub.cancelled:
                return True

            return False

        return True

    def can_upgrade(self):
        """User who has lifetime licence or giveaway manual subscriptions can decide to upgrade to a paid plan"""
        sub: Subscription = self.get_subscription()
        # user who has canceled can also re-subscribe
        if sub and not sub.cancelled:
            return False

        apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=self.id)
        if apple_sub and apple_sub.is_valid():
            return False

        manual_sub: ManualSubscription = ManualSubscription.get_by(user_id=self.id)
        # user who has giveaway premium can decide to upgrade
        if (
            manual_sub
            and manual_sub.end_at > arrow.now()
            and not manual_sub.is_giveaway
        ):
            return False

        return True

    def is_premium(self) -> bool:
        """
        user is premium if they:
        - have a lifetime deal or
        - in trial period or
        - active subscription
        """
        if self._lifetime_or_active_subscription():
            return True

        if self.trial_end and arrow.now() < self.trial_end:
            return True

        return False

    def can_create_new_alias(self) -> bool:
        if self.is_premium():
            return True

        return Alias.filter_by(user_id=self.id).count() < MAX_NB_EMAIL_FREE_PLAN

    def set_password(self, password):
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password.encode(), salt).decode()
        self.salt = salt.decode()
        self.password = password_hash

    def check_password(self, password) -> bool:
        if not self.password:
            return False
        password_hash = bcrypt.hashpw(password.encode(), self.salt.encode())
        return self.password.encode() == password_hash

    def profile_picture_url(self):
        if self.profile_picture_id:
            return self.profile_picture.get_url()
        else:
            return url_for("static", filename="default-avatar.png")

    def suggested_emails(self, website_name) -> (str, [str]):
        """return suggested email and other email choices """
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
        """return suggested name and other name choices """
        other_name = convert_to_id(self.name)

        return self.name, [other_name, "Anonymous", "whoami"]

    def get_name_initial(self) -> str:
        names = self.name.split(" ")
        return "".join([n[0].upper() for n in names if n])

    def get_subscription(self) -> "Subscription":
        """return *active* subscription
        TODO: support user unsubscribe and re-subscribe
        """
        sub = Subscription.get_by(user_id=self.id)
        # TODO: sub is active only if sub.next_bill_date > now
        # due to a bug on next_bill_date, wait until next month (May 8)
        # when all next_bill_date are correctly updated to add this check

        if sub and sub.cancelled:
            # sub is active until the next billing_date + 1
            if sub.next_bill_date >= arrow.now().shift(days=-1).date():
                return sub
            # past subscription, user is considered not having a subscription = free plan
            else:
                return None
        else:
            return sub

    def verified_custom_domains(self):
        return CustomDomain.query.filter_by(user_id=self.id, verified=True).all()

    def mailboxes(self) -> List["Mailbox"]:
        """list of mailbox that user own"""
        mailboxes = []

        for mailbox in Mailbox.query.filter_by(user_id=self.id, verified=True):
            mailboxes.append(mailbox)

        return mailboxes

    def nb_directory(self):
        return Directory.query.filter_by(user_id=self.id).count()

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


class ActivationCode(db.Model, ModelMixin):
    """For activate user account"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    code = db.Column(db.String(128), unique=True, nullable=False)

    user = db.relationship(User)

    expired = db.Column(ArrowType, nullable=False, default=_expiration_1h)

    def is_expired(self):
        return self.expired < arrow.now()


class ResetPasswordCode(db.Model, ModelMixin):
    """For resetting password"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    code = db.Column(db.String(128), unique=True, nullable=False)

    user = db.relationship(User)

    expired = db.Column(ArrowType, nullable=False, default=_expiration_1h)

    def is_expired(self):
        return self.expired < arrow.now()


class SocialAuth(db.Model, ModelMixin):
    """Store how user authenticates with social login"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    # name of the social login used, could be facebook, google or github
    social = db.Column(db.String(128), nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "social", name="uq_social_auth"),)


# <<< OAUTH models >>>


def generate_oauth_client_id(client_name) -> str:
    oauth_client_id = convert_to_id(client_name) + "-" + random_string()

    # check that the client does not exist yet
    if not Client.get_by(oauth_client_id=oauth_client_id):
        LOG.debug("generate oauth_client_id %s", oauth_client_id)
        return oauth_client_id

    # Rerun the function
    LOG.warning(
        "client_id %s already exists, generate a new client_id", oauth_client_id
    )
    return generate_oauth_client_id(client_name)


class MfaBrowser(db.Model, ModelMixin):
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    token = db.Column(db.String(64), default=False, unique=True, nullable=False)
    expires = db.Column(ArrowType, default=False, nullable=False)

    user = db.relationship(User)

    @classmethod
    def create_new(cls, user, token_length=64) -> "MfaBrowser":
        found = False
        while not found:
            token = random_string(token_length)

            if not cls.get_by(token=token):
                found = True

        return MfaBrowser.create(
            user_id=user.id, token=token, expires=arrow.now().shift(days=30),
        )

    @classmethod
    def delete(cls, token):
        cls.query.filter(cls.token == token).delete()
        db.session.commit()

    @classmethod
    def delete_expired(cls):
        cls.query.filter(cls.expires < arrow.now()).delete()
        db.session.commit()

    def is_expired(self):
        return self.expires < arrow.now()

    def reset_expire(self):
        self.expires = arrow.now().shift(days=30)


class Client(db.Model, ModelMixin):
    oauth_client_id = db.Column(db.String(128), unique=True, nullable=False)
    oauth_client_secret = db.Column(db.String(128), nullable=False)

    name = db.Column(db.String(128), nullable=False)
    home_url = db.Column(db.String(1024))
    published = db.Column(db.Boolean, default=False, nullable=False)

    # user who created this client
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    icon_id = db.Column(db.ForeignKey(File.id), nullable=True)

    icon = db.relationship(File)

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
            return URL + "/static/default-icon.svg"

    def last_user_login(self) -> "ClientUser":
        client_user = (
            ClientUser.query.filter(ClientUser.client_id == self.id)
            .order_by(ClientUser.updated_at)
            .first()
        )
        if client_user:
            return client_user
        return None


class RedirectUri(db.Model, ModelMixin):
    """Valid redirect uris for a client"""

    client_id = db.Column(db.ForeignKey(Client.id, ondelete="cascade"), nullable=False)
    uri = db.Column(db.String(1024), nullable=False)

    client = db.relationship(Client, backref="redirect_uris")


class AuthorizationCode(db.Model, ModelMixin):
    code = db.Column(db.String(128), unique=True, nullable=False)
    client_id = db.Column(db.ForeignKey(Client.id, ondelete="cascade"), nullable=False)
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    scope = db.Column(db.String(128))
    redirect_uri = db.Column(db.String(1024))

    # what is the input response_type, e.g. "code", "code,id_token", ...
    response_type = db.Column(db.String(128))

    user = db.relationship(User, lazy=False)
    client = db.relationship(Client, lazy=False)

    expired = db.Column(ArrowType, nullable=False, default=_expiration_5m)

    def is_expired(self):
        return self.expired < arrow.now()


class OauthToken(db.Model, ModelMixin):
    access_token = db.Column(db.String(128), unique=True)
    client_id = db.Column(db.ForeignKey(Client.id, ondelete="cascade"), nullable=False)
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    scope = db.Column(db.String(128))
    redirect_uri = db.Column(db.String(1024))

    # what is the input response_type, e.g. "token", "token,id_token", ...
    response_type = db.Column(db.String(128))

    user = db.relationship(User)
    client = db.relationship(Client)

    expired = db.Column(ArrowType, nullable=False, default=_expiration_1h)

    def is_expired(self):
        return self.expired < arrow.now()


def generate_email(
    scheme: int = AliasGeneratorEnum.word.value, in_hex: bool = False
) -> str:
    """generate an email address that does not exist before
    :param scheme: int, value of AliasGeneratorEnum, indicate how the email is generated
    :type in_hex: bool, if the generate scheme is uuid, is hex favorable?
    """
    if scheme == AliasGeneratorEnum.uuid.value:
        name = uuid.uuid4().hex if in_hex else uuid.uuid4().__str__()
        random_email = name + "@" + FIRST_ALIAS_DOMAIN
    else:
        random_email = random_words() + "@" + FIRST_ALIAS_DOMAIN

    random_email = random_email.lower().strip()

    # check that the client does not exist yet
    if not Alias.get_by(email=random_email) and not DeletedAlias.get_by(
        email=random_email
    ):
        LOG.debug("generate email %s", random_email)
        return random_email

    # Rerun the function
    LOG.warning("email %s already exists, generate a new email", random_email)
    return generate_email(scheme=scheme, in_hex=in_hex)


class Alias(db.Model, ModelMixin):
    """Alias"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)

    # the name to use when user replies/sends from alias
    name = db.Column(db.String(128), nullable=True, default=None)

    enabled = db.Column(db.Boolean(), default=True, nullable=False)

    custom_domain_id = db.Column(
        db.ForeignKey("custom_domain.id", ondelete="cascade"), nullable=True
    )

    custom_domain = db.relationship("CustomDomain", foreign_keys=[custom_domain_id])

    # To know whether an alias is created "on the fly", i.e. via the custom domain catch-all feature
    automatic_creation = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )

    # to know whether an alias belongs to a directory
    directory_id = db.Column(
        db.ForeignKey("directory.id", ondelete="cascade"), nullable=True
    )

    note = db.Column(db.Text, default=None, nullable=True)

    # an alias can be owned by another mailbox
    mailbox_id = db.Column(
        db.ForeignKey("mailbox.id", ondelete="cascade"), nullable=False
    )

    # prefix _ to avoid this object being used accidentally.
    # To have the list of all mailboxes, should use AliasInfo instead
    _mailboxes = db.relationship("Mailbox", secondary="alias_mailbox", lazy="joined")

    # If the mailbox has PGP-enabled, user can choose disable the PGP on the alias
    # this is useful when some senders already support PGP
    disable_pgp = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )

    user = db.relationship(User)
    mailbox = db.relationship("Mailbox", lazy="joined")

    @property
    def mailboxes(self):
        ret = [self.mailbox]
        for m in self._mailboxes:
            ret.append(m)

        return ret

    def mailbox_support_pgp(self) -> bool:
        """return True of one of the mailboxes support PGP"""
        for mb in self.mailboxes:
            if mb.pgp_finger_print:
                return True
        return False

    def pgp_enabled(self) -> bool:
        if self.mailbox_support_pgp() and not self.disable_pgp:
            return True
        return False

    @classmethod
    def create(cls, **kw):
        r = cls(**kw)

        # make sure alias is not in global trash, i.e. DeletedAlias table
        email = kw["email"]
        if DeletedAlias.get_by(email=email):
            raise AliasInTrashError

        if DomainDeletedAlias.get_by(email=email):
            raise AliasInTrashError

        db.session.add(r)
        return r

    @classmethod
    def create_new(cls, user, prefix, note=None, mailbox_id=None):
        if not prefix:
            raise Exception("alias prefix cannot be empty")

        # find the right suffix - avoid infinite loop by running this at max 1000 times
        for i in range(1000):
            suffix = random_word()
            email = f"{prefix}.{suffix}@{FIRST_ALIAS_DOMAIN}"

            if not cls.get_by(email=email) and not DeletedAlias.get_by(email=email):
                break

        return Alias.create(
            user_id=user.id,
            email=email,
            note=note,
            mailbox_id=mailbox_id or user.default_mailbox_id,
        )

    @classmethod
    def create_new_random(
        cls,
        user,
        scheme: int = AliasGeneratorEnum.word.value,
        in_hex: bool = False,
        note: str = None,
    ):
        """create a new random alias"""
        random_email = generate_email(scheme=scheme, in_hex=in_hex)
        return Alias.create(
            user_id=user.id,
            email=random_email,
            mailbox_id=user.default_mailbox_id,
            note=note,
        )

    def mailbox_email(self):
        if self.mailbox_id:
            return self.mailbox.email
        else:
            return self.user.email

    def get_contacts(self, page=0):
        contacts = (
            Contact.filter_by(alias_id=self.id)
            .order_by(Contact.created_at)
            .limit(PAGE_LIMIT)
            .offset(page * PAGE_LIMIT)
            .all()
        )
        return contacts

    def __repr__(self):
        return f"<Alias {self.id} {self.email}>"


class ClientUser(db.Model, ModelMixin):
    __table_args__ = (
        db.UniqueConstraint("user_id", "client_id", name="uq_client_user"),
    )

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    client_id = db.Column(db.ForeignKey(Client.id, ondelete="cascade"), nullable=False)

    # Null means client has access to user original email
    alias_id = db.Column(db.ForeignKey(Alias.id, ondelete="cascade"), nullable=True)

    # user can decide to send to client another name
    name = db.Column(
        db.String(128), nullable=True, default=None, server_default=text("NULL")
    )

    # user can decide to send to client a default avatar
    default_avatar = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )

    alias = db.relationship(Alias, backref="client_users")

    user = db.relationship(User)
    client = db.relationship(Client)

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
                    res[Scope.NAME.value] = self.name
                else:
                    res[Scope.NAME.value] = self.user.name
            elif scope == Scope.AVATAR_URL:
                if self.user.profile_picture_id:
                    if self.default_avatar:
                        res[Scope.AVATAR_URL.value] = URL + "/static/default-avatar.png"
                    else:
                        res[Scope.AVATAR_URL.value] = self.user.profile_picture.get_url(
                            AVATAR_URL_EXPIRATION
                        )
                else:
                    res[Scope.AVATAR_URL.value] = None
            elif scope == Scope.EMAIL:
                # Use generated email
                if self.alias_id:
                    LOG.debug(
                        "Use gen email for user %s, client %s", self.user, self.client
                    )
                    res[Scope.EMAIL.value] = self.alias.email
                # Use user original email
                else:
                    res[Scope.EMAIL.value] = self.user.email

        return res


class Contact(db.Model, ModelMixin):
    """
    Store configuration of sender (website-email) and alias.
    """

    __table_args__ = (
        db.UniqueConstraint("alias_id", "website_email", name="uq_contact"),
    )

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    alias_id = db.Column(db.ForeignKey(Alias.id, ondelete="cascade"), nullable=False)

    name = db.Column(
        db.String(512), nullable=True, default=None, server_default=text("NULL")
    )

    website_email = db.Column(db.String(512), nullable=False)

    # the email from header, e.g. AB CD <ab@cd.com>
    # nullable as this field is added after website_email
    website_from = db.Column(db.String(1024), nullable=True)

    # when user clicks on "reply", they will reply to this address.
    # This address allows to hide user personal email
    # this reply email is created every time a website sends an email to user
    # it has the prefix "reply+" to distinguish with other email
    reply_email = db.Column(db.String(512), nullable=False)

    # whether a contact is created via CC
    is_cc = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    alias = db.relationship(Alias)
    user = db.relationship(User)

    def website_send_to(self):
        """return the email address with name.
        to use when user wants to send an email from the alias
        Return
        "First Last | email at example.com" <ra+random_string@SL>
        """

        # Prefer using contact name if possible
        name = self.name

        # if no name, try to parse it from website_from
        if not name and self.website_from:
            try:
                from app.email_utils import parseaddr_unicode

                name, _ = parseaddr_unicode(self.website_from)
            except Exception:
                # Skip if website_from is wrongly formatted
                LOG.warning(
                    "Cannot parse contact %s website_from %s", self, self.website_from
                )
                name = ""

        # remove all double quote
        if name:
            name = name.replace('"', "")

        if name:
            name = name + " | " + self.website_email.replace("@", " at ")
        else:
            name = self.website_email.replace("@", " at ")

        # cannot use formataddr here as this field is for email client, not for MTA
        return f'"{name}" <{self.reply_email}>'

    def new_addr(self):
        """
        Replace original email by reply_email. Possible formats:
        - first@example.com via SimpleLogin <reply_email> OR
        - First Last - first at example.com <reply_email> OR
        - First Last - first(a)example.com <reply_email> OR
        - First Last - first@example.com <reply_email> OR
        And return new address with RFC 2047 format

        `new_email` is a special reply address
        """
        user = self.user
        if (
            not user
            or not SenderFormatEnum.has_value(user.sender_format)
            or user.sender_format == SenderFormatEnum.VIA.value
        ):
            new_name = f"{self.website_email} via SimpleLogin"
        elif user.sender_format == SenderFormatEnum.AT.value:
            name = self.name or ""
            new_name = (
                name + (" - " if name else "") + self.website_email.replace("@", " at ")
            ).strip()
        elif user.sender_format == SenderFormatEnum.A.value:
            name = self.name or ""
            new_name = (
                name + (" - " if name else "") + self.website_email.replace("@", "(a)")
            ).strip()
        elif user.sender_format == SenderFormatEnum.FULL.value:
            name = self.name or ""
            new_name = (name + (" - " if name else "") + self.website_email).strip()

        new_addr = formataddr((new_name, self.reply_email)).strip()
        return new_addr.strip()

    def last_reply(self) -> "EmailLog":
        """return the most recent reply"""
        return (
            EmailLog.query.filter_by(contact_id=self.id, is_reply=True)
            .order_by(desc(EmailLog.created_at))
            .first()
        )

    def __repr__(self):
        return f"<Contact {self.id} {self.website_email} {self.alias_id}>"


class EmailLog(db.Model, ModelMixin):
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    contact_id = db.Column(
        db.ForeignKey(Contact.id, ondelete="cascade"), nullable=False
    )

    # whether this is a reply
    is_reply = db.Column(db.Boolean, nullable=False, default=False)

    # for ex if alias is disabled, this forwarding is blocked
    blocked = db.Column(db.Boolean, nullable=False, default=False)

    # can happen when user email service refuses the forwarded email
    # usually because the forwarded email is too spammy
    bounced = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    # SpamAssassin result
    is_spam = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    spam_status = db.Column(db.Text, nullable=True, default=None)

    # Point to the email that has been refused
    refused_email_id = db.Column(
        db.ForeignKey("refused_email.id", ondelete="SET NULL"), nullable=True
    )

    # in case of bounce, record on what mailbox the email has been bounced
    # useful when an alias has several mailboxes
    bounced_mailbox_id = db.Column(
        db.ForeignKey("mailbox.id", ondelete="cascade"), nullable=True
    )

    refused_email = db.relationship("RefusedEmail")
    forward = db.relationship(Contact)

    contact = db.relationship(Contact)

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


class Subscription(db.Model, ModelMixin):
    # Come from Paddle
    cancel_url = db.Column(db.String(1024), nullable=False)
    update_url = db.Column(db.String(1024), nullable=False)
    subscription_id = db.Column(db.String(1024), nullable=False, unique=True)
    event_time = db.Column(ArrowType, nullable=False)
    next_bill_date = db.Column(db.Date, nullable=False)

    cancelled = db.Column(db.Boolean, nullable=False, default=False)

    plan = db.Column(db.Enum(PlanEnum), nullable=False)

    user_id = db.Column(
        db.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )

    user = db.relationship(User)

    def plan_name(self):
        if self.plan == PlanEnum.monthly:
            return "Monthly ($2.99/month)"
        else:
            return "Yearly ($29.99/year)"


class ManualSubscription(db.Model, ModelMixin):
    """
    For users who use other forms of payment and therefore not pass by Paddle
    """

    user_id = db.Column(
        db.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )

    # an reminder is sent several days before the subscription ends
    end_at = db.Column(ArrowType, nullable=False)

    # for storing note about this subscription
    comment = db.Column(db.Text, nullable=True)

    # manual subscription are also used for Premium giveaways
    is_giveaway = db.Column(
        db.Boolean, default=False, nullable=False, server_default="0"
    )

    user = db.relationship(User)


# https://help.apple.com/app-store-connect/#/dev58bda3212
_APPLE_GRACE_PERIOD_DAYS = 16


class AppleSubscription(db.Model, ModelMixin):
    """
    For users who have subscribed via Apple in-app payment
    """

    user_id = db.Column(
        db.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )

    expires_date = db.Column(ArrowType, nullable=False)

    # to avoid using "Restore Purchase" on another account
    original_transaction_id = db.Column(db.String(256), nullable=False, unique=True)
    receipt_data = db.Column(db.Text(), nullable=False)

    plan = db.Column(db.Enum(PlanEnum), nullable=False)

    user = db.relationship(User)

    def is_valid(self):
        # Todo: take into account grace period?
        return self.expires_date > arrow.now().shift(days=-_APPLE_GRACE_PERIOD_DAYS)


class DeletedAlias(db.Model, ModelMixin):
    """Store all deleted alias to make sure they are NOT reused"""

    email = db.Column(db.String(256), unique=True, nullable=False)

    def __repr__(self):
        return f"<Deleted Alias {self.email}>"


class EmailChange(db.Model, ModelMixin):
    """Used when user wants to update their email"""

    user_id = db.Column(
        db.ForeignKey(User.id, ondelete="cascade"),
        nullable=False,
        unique=True,
        index=True,
    )
    new_email = db.Column(db.String(256), unique=True, nullable=False)
    code = db.Column(db.String(128), unique=True, nullable=False)
    expired = db.Column(ArrowType, nullable=False, default=_expiration_12h)

    user = db.relationship(User)

    def is_expired(self):
        return self.expired < arrow.now()


class AliasUsedOn(db.Model, ModelMixin):
    """Used to know where an alias is created"""

    __table_args__ = (
        db.UniqueConstraint("alias_id", "hostname", name="uq_alias_used"),
    )

    alias_id = db.Column(db.ForeignKey(Alias.id, ondelete="cascade"), nullable=False)
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    alias = db.relationship(Alias)

    hostname = db.Column(db.String(1024), nullable=False)


class ApiKey(db.Model, ModelMixin):
    """used in browser extension to identify user"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    code = db.Column(db.String(128), unique=True, nullable=False)
    name = db.Column(db.String(128), nullable=False)
    last_used = db.Column(ArrowType, default=None)
    times = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship(User)

    @classmethod
    def create(cls, user_id, name):
        # generate unique code
        found = False
        while not found:
            code = random_string(60)

            if not cls.get_by(code=code):
                found = True

        a = cls(user_id=user_id, code=code, name=name)
        db.session.add(a)
        return a


class CustomDomain(db.Model, ModelMixin):
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    domain = db.Column(db.String(128), unique=True, nullable=False)

    # default name to use when user replies/sends from alias
    name = db.Column(db.String(128), nullable=True, default=None)

    verified = db.Column(db.Boolean, nullable=False, default=False)
    dkim_verified = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )
    spf_verified = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )
    dmarc_verified = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )

    # an alias is created automatically the first time it receives an email
    catch_all = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    user = db.relationship(User)

    def nb_alias(self):
        return Alias.filter_by(custom_domain_id=self.id).count()

    def __repr__(self):
        return f"<Custom Domain {self.domain}>"


class DomainDeletedAlias(db.Model, ModelMixin):
    """Store all deleted alias for a domain"""

    __table_args__ = (
        db.UniqueConstraint("domain_id", "email", name="uq_domain_trash"),
    )

    email = db.Column(db.String(256), nullable=False)
    domain_id = db.Column(
        db.ForeignKey("custom_domain.id", ondelete="cascade"), nullable=False
    )
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)


class LifetimeCoupon(db.Model, ModelMixin):
    code = db.Column(db.String(128), nullable=False, unique=True)
    nb_used = db.Column(db.Integer, nullable=False)


class Directory(db.Model, ModelMixin):
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    name = db.Column(db.String(128), unique=True, nullable=False)

    user = db.relationship(User)

    def nb_alias(self):
        return Alias.filter_by(directory_id=self.id).count()

    @classmethod
    def delete(cls, obj_id):
        # Put all aliases belonging to this directory to global trash
        try:
            for alias in Alias.query.filter_by(directory_id=obj_id):
                DeletedAlias.create(email=alias.email)
            db.session.commit()
        # this can happen when a previously deleted alias is re-created via catch-all or directory feature
        except IntegrityError:
            LOG.error("Some aliases have been added before to DeletedAlias")
            db.session.rollback()

        cls.query.filter(cls.id == obj_id).delete()
        db.session.commit()

    def __repr__(self):
        return f"<Directory {self.name}>"


class Job(db.Model, ModelMixin):
    """Used to schedule one-time job in the future"""

    name = db.Column(db.String(128), nullable=False)
    payload = db.Column(db.JSON)

    # whether the job has been taken by the job runner
    taken = db.Column(db.Boolean, default=False, nullable=False)
    run_at = db.Column(ArrowType)

    def __repr__(self):
        return f"<Job {self.id} {self.name} {self.payload}>"


class Mailbox(db.Model, ModelMixin):
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    email = db.Column(db.String(256), nullable=False)
    verified = db.Column(db.Boolean, default=False, nullable=False)
    force_spf = db.Column(db.Boolean, default=True, server_default="1", nullable=False)

    # used when user wants to update mailbox email
    new_email = db.Column(db.String(256), unique=True)

    pgp_public_key = db.Column(db.Text, nullable=True)
    pgp_finger_print = db.Column(db.String(512), nullable=True)

    __table_args__ = (db.UniqueConstraint("user_id", "email", name="uq_mailbox_user"),)

    def nb_alias(self):
        return Alias.filter_by(mailbox_id=self.id).count()

    @classmethod
    def delete(cls, obj_id):
        # Put all aliases belonging to this mailbox to global trash
        try:
            for alias in Alias.query.filter_by(mailbox_id=obj_id):
                # special handling for alias that has several mailboxes and has mailbox_id=obj_id
                if len(alias.mailboxes) > 1:
                    # use the first mailbox found in alias._mailboxes
                    first_mb = alias._mailboxes[0]
                    alias.mailbox_id = first_mb.id
                    alias._mailboxes.remove(first_mb)
                else:
                    # only put aliases that have mailbox as a single mailbox into trash
                    DeletedAlias.create(email=alias.email)
                db.session.commit()
        # this can happen when a previously deleted alias is re-created via catch-all or directory feature
        except IntegrityError:
            LOG.error("Some aliases have been added before to DeletedAlias")
            db.session.rollback()

        cls.query.filter(cls.id == obj_id).delete()
        db.session.commit()

    def __repr__(self):
        return f"<Mailbox {self.email}>"


class AccountActivation(db.Model, ModelMixin):
    """contains code to activate the user account when they sign up on mobile"""

    user_id = db.Column(
        db.ForeignKey(User.id, ondelete="cascade"), nullable=False, unique=True
    )
    # the activation code is usually 6 digits
    code = db.Column(db.String(10), nullable=False)

    # nb tries decrements each time user enters wrong code
    tries = db.Column(db.Integer, default=3, nullable=False)

    __table_args__ = (
        CheckConstraint(tries >= 0, name="account_activation_tries_positive"),
        {},
    )


class RefusedEmail(db.Model, ModelMixin):
    """Store emails that have been refused, i.e. bounced or classified as spams"""

    # Store the full report, including logs from Sending & Receiving MTA
    full_report_path = db.Column(db.String(128), unique=True, nullable=False)

    # The original email, to display to user
    path = db.Column(db.String(128), unique=True, nullable=True)

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)

    # the email content will be deleted at this date
    delete_at = db.Column(ArrowType, nullable=False, default=_expiration_7d)

    # toggle this when email content (stored at full_report_path & path are deleted)
    deleted = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    def get_url(self, expires_in=3600):
        if self.path:
            return s3.get_url(self.path, expires_in)
        else:
            return s3.get_url(self.full_report_path, expires_in)

    def __repr__(self):
        return f"<Refused Email {self.id} {self.path} {self.delete_at}>"


class Referral(db.Model, ModelMixin):
    """Referral code so user can invite others"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    name = db.Column(db.String(512), nullable=True, default=None)

    code = db.Column(db.String(128), unique=True, nullable=False)

    def nb_user(self):
        return User.filter_by(referral_id=self.id, activated=True).count()

    def link(self):
        return f"{LANDING_PAGE_URL}?slref={self.code}"


class SentAlert(db.Model, ModelMixin):
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

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    to_email = db.Column(db.String(256), nullable=False)
    alert_type = db.Column(db.String(256), nullable=False)


class AliasMailbox(db.Model, ModelMixin):
    __table_args__ = (
        db.UniqueConstraint("alias_id", "mailbox_id", name="uq_alias_mailbox"),
    )

    alias_id = db.Column(db.ForeignKey(Alias.id, ondelete="cascade"), nullable=False)
    mailbox_id = db.Column(
        db.ForeignKey(Mailbox.id, ondelete="cascade"), nullable=False
    )


_NB_RECOVERY_CODE = 8
_RECOVERY_CODE_LENGTH = 8


class RecoveryCode(db.Model, ModelMixin):
    """allow user to login in case you lose any of your authenticators"""

    __table_args__ = (db.UniqueConstraint("user_id", "code", name="uq_recovery_code"),)

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    code = db.Column(db.String(16), nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)
    used_at = db.Column(ArrowType, nullable=True, default=None)

    user = db.relationship(User)

    @classmethod
    def generate(cls, user):
        """generate recovery codes for user"""
        # delete all existing codes
        cls.query.filter_by(user_id=user.id).delete()
        db.session.flush()

        nb_code = 0
        while nb_code < _NB_RECOVERY_CODE:
            code = random_string(_RECOVERY_CODE_LENGTH)
            if not cls.get_by(user_id=user.id, code=code):
                cls.create(user_id=user.id, code=code)
                nb_code += 1

        LOG.d("Create recovery codes for %s", user)
        db.session.commit()

    @classmethod
    def empty(cls, user):
        """Delete all recovery codes for user"""
        cls.query.filter_by(user_id=user.id).delete()
        db.session.commit()


class Notification(db.Model, ModelMixin):
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    message = db.Column(db.Text, nullable=False)

    # whether user has marked the notification as read
    read = db.Column(db.Boolean, nullable=False, default=False)
