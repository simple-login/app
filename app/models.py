import enum
import random
import uuid
from email.utils import parseaddr, formataddr

import arrow
import bcrypt
from flask import url_for
from flask_login import UserMixin
from sqlalchemy import text, desc, CheckConstraint
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
)
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
    user_id = db.Column(db.ForeignKey("users.id", ondelete="cascade"), nullable=False)

    def get_url(self, expires_in=3600):
        return s3.get_url(self.path, expires_in)


class PlanEnum(enum.Enum):
    monthly = 2
    yearly = 3


class AliasGeneratorEnum(enum.Enum):
    word = 1  # aliases are generated based on random words
    uuid = 2  # aliases are generated based on uuid

    @classmethod
    def has_value(cls, value: int) -> bool:
        return value in set(item.value for item in cls)


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

    # some users could have lifetime premium
    lifetime = db.Column(db.Boolean, default=False, nullable=False, server_default="0")

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

    # Use the "via" format for sender address, i.e. "name@example.com via SimpleLogin"
    # If False, use the format "Name - name at example.com"
    use_via_format_for_sender = db.Column(
        db.Boolean, default=True, nullable=False, server_default="1"
    )

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

    def lifetime_or_active_subscription(self) -> bool:
        """True if user has lifetime licence or active subscription"""
        if self.lifetime:
            return True

        sub: Subscription = self.get_subscription()
        if sub:
            return True

        manual_sub: ManualSubscription = ManualSubscription.get_by(user_id=self.id)
        if manual_sub and manual_sub.end_at > arrow.now():
            return True

        return False

    def in_trial(self):
        """return True if user does not have lifetime licence or an active subscription AND is in trial period"""
        if self.lifetime_or_active_subscription():
            return False

        if self.trial_end and arrow.now() < self.trial_end:
            return True

        return False

    def should_upgrade(self):
        if self.lifetime_or_active_subscription():
            # user who has canceled can also re-subscribe
            sub: Subscription = self.get_subscription()
            if sub and sub.cancelled:
                return True

            return False

        return True

    def next_bill_date(self) -> str:
        sub: Subscription = self.get_subscription()
        if sub:
            return sub.next_bill_date.strftime("%Y-%m-%d")

        LOG.error(
            f"next_bill_date() should be called only on user with active subscription. User {self}"
        )
        return ""

    def is_cancel(self) -> bool:
        """User has canceled their subscription but the subscription is still active,
        i.e. next_bill_date > now"""
        sub: Subscription = self.get_subscription()
        if sub and sub.cancelled:
            return True

        return False

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

        all_aliases = [ge.email for ge in Alias.filter_by(user_id=self.id)]
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

    def get_subscription(self):
        """return *active* subscription
        TODO: support user unsubscribe and re-subscribe
        """
        sub = Subscription.get_by(user_id=self.id)
        # TODO: sub is active only if sub.next_bill_date > now
        # due to a bug on next_bill_date, wait until next month (April 8)
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

    def mailboxes(self) -> [str]:
        """list of mailbox emails that user own"""
        mailboxes = []

        for mailbox in Mailbox.query.filter_by(user_id=self.id, verified=True):
            mailboxes.append(mailbox.email)

        return mailboxes

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
        random_email = name + "@" + EMAIL_DOMAIN
    else:
        random_email = random_words() + "@" + EMAIL_DOMAIN

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

    enabled = db.Column(db.Boolean(), default=True, nullable=False)

    custom_domain_id = db.Column(
        db.ForeignKey("custom_domain.id", ondelete="cascade"), nullable=True
    )

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

    user = db.relationship(User)
    mailbox = db.relationship("Mailbox")

    @classmethod
    def create_new(cls, user, prefix, note=None, mailbox_id=None):
        if not prefix:
            raise Exception("alias prefix cannot be empty")

        # find the right suffix - avoid infinite loop by running this at max 1000 times
        for i in range(1000):
            suffix = random_word()
            email = f"{prefix}.{suffix}@{EMAIL_DOMAIN}"

            if not cls.get_by(email=email):
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

    alias = db.relationship(Alias, backref="contacts")
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
        Replace original email by reply_email. 2 possible formats:
        - first@example.com by SimpleLogin <reply_email> OR
        - First Last - first at example.com <reply_email>
        And return new address with RFC 2047 format

        `new_email` is a special reply address
        """
        user = self.user
        if user.use_via_format_for_sender:
            new_name = f"{self.website_email} via SimpleLogin"
        else:
            name = self.name or ""
            new_name = (
                name + (" - " if name else "") + self.website_email.replace("@", " at ")
            ).strip()

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

    refused_email = db.relationship("RefusedEmail")
    forward = db.relationship(Contact)

    contact = db.relationship(Contact)

    def get_action(self) -> str:
        """return the action name: forward|reply|block|bounced"""
        if self.is_reply:
            return "reply"
        elif self.bounced:
            return "bounced"
        elif self.blocked:
            return "blocked"
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

    user = db.relationship(User)


class DeletedAlias(db.Model, ModelMixin):
    """Store all deleted alias to make sure they are NOT reused"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    email = db.Column(db.String(256), unique=True, nullable=False)


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

    verified = db.Column(db.Boolean, nullable=False, default=False)
    dkim_verified = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )
    spf_verified = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )

    # an alias is created automatically the first time it receives an email
    catch_all = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    user = db.relationship(User)

    def nb_alias(self):
        return Alias.filter_by(custom_domain_id=self.id).count()

    def __repr__(self):
        return f"<Custom Domain {self.domain}>"


class LifetimeCoupon(db.Model, ModelMixin):
    code = db.Column(db.String(128), nullable=False, unique=True)
    nb_used = db.Column(db.Integer, nullable=False)


class Directory(db.Model, ModelMixin):
    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    name = db.Column(db.String(128), unique=True, nullable=False)

    user = db.relationship(User)

    def nb_alias(self):
        return Alias.filter_by(directory_id=self.id).count()

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
    email = db.Column(db.String(256), unique=True, nullable=False)
    verified = db.Column(db.Boolean, default=False, nullable=False)

    # used when user wants to update mailbox email
    new_email = db.Column(db.String(256), unique=True)

    pgp_public_key = db.Column(db.Text, nullable=True)
    pgp_finger_print = db.Column(db.String(512), nullable=True)

    def nb_alias(self):
        return Alias.filter_by(mailbox_id=self.id).count()

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
