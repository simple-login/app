import enum
import random
import uuid

import arrow
import bcrypt
from flask import url_for
from flask_login import UserMixin
from sqlalchemy import text, desc
from sqlalchemy_utils import ArrowType

from app import s3
from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN, URL, AVATAR_URL_EXPIRATION
from app.email_utils import get_email_name
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
    email = db.Column(db.String(128), unique=True, nullable=False)
    salt = db.Column(db.String(128), nullable=False)
    password = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    alias_generator = db.Column(db.Integer, nullable=False, default=AliasGeneratorEnum.word.value)

    activated = db.Column(db.Boolean, default=False, nullable=False)

    profile_picture_id = db.Column(db.ForeignKey(File.id), nullable=True)

    otp_secret = db.Column(db.String(16), nullable=True)
    enable_otp = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )

    profile_picture = db.relationship(File)

    @classmethod
    def create(cls, email, name, password=None, **kwargs):
        user = super(User, cls).create(email=email, name=name, **kwargs)

        if not password:
            # set a random password
            password = random_string(20)

        user.set_password(password)
        db.session.flush()

        # create a first alias mail to show user how to use when they login
        GenEmail.create_new(user.id, prefix="my-first-alias")
        db.session.flush()

        return user

    def should_upgrade(self):
        return not self.is_premium()

    def is_premium(self):
        """user is premium if they have a active subscription"""
        sub: Subscription = self.get_subscription()
        if sub:
            if sub.cancelled:
                # user is premium until the next billing_date + 1
                return sub.next_bill_date >= arrow.now().shift(days=-1).date()

            # subscription active, ie not cancelled
            return True

        return False

    def can_create_new_alias(self):
        if self.is_premium():
            return True

        return GenEmail.filter_by(user_id=self.id).count() < MAX_NB_EMAIL_FREE_PLAN

    def set_password(self, password):
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password.encode(), salt).decode()
        self.salt = salt.decode()
        self.password = password_hash

    def check_password(self, password) -> bool:
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

        all_gen_emails = [ge.email for ge in GenEmail.filter_by(user_id=self.id)]
        if self.can_create_new_alias():
            suggested_gen_email = GenEmail.create_new(
                self.id, prefix=website_name
            ).email
        else:
            # pick an email from the list of gen emails
            suggested_gen_email = random.choice(all_gen_emails)

        return (
            suggested_gen_email,
            list(set(all_gen_emails).difference({suggested_gen_email})),
        )

    def suggested_names(self) -> (str, [str]):
        """return suggested name and other name choices """

        other_name = convert_to_id(self.name)

        return self.name, [other_name, "Anonymous", "whoami"]

    def get_name_initial(self) -> str:
        names = self.name.split(" ")
        return "".join([n[0].upper() for n in names if n])

    def plan_name(self) -> str:
        if self.is_premium():
            sub = self.get_subscription()

            if sub.plan == PlanEnum.monthly:
                return "Monthly ($2.99/month)"
            else:
                return "Yearly ($29.99/year)"
        else:
            return "Free Plan"

    def get_subscription(self):
        sub = Subscription.get_by(user_id=self.id)
        return sub

    def verified_custom_domains(self):
        return CustomDomain.query.filter_by(user_id=self.id, verified=True).all()

    def __repr__(self):
        return f"<User {self.id} {self.name} {self.email}>"


def _expiration_1h():
    return arrow.now().shift(hours=1)


def _expiration_12h():
    return arrow.now().shift(hours=12)


def _expiration_5m():
    return arrow.now().shift(minutes=5)


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


def generate_email(scheme: int = AliasGeneratorEnum.word.value, in_hex: bool = False) -> str:
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
    if not GenEmail.get_by(email=random_email) and not DeletedAlias.get_by(
            email=random_email
    ):
        LOG.debug("generate email %s", random_email)
        return random_email

    # Rerun the function
    LOG.warning("email %s already exists, generate a new email", random_email)
    return generate_email(scheme=scheme, in_hex=in_hex)


class GenEmail(db.Model, ModelMixin):
    """Generated email"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)

    enabled = db.Column(db.Boolean(), default=True, nullable=False)

    custom_domain_id = db.Column(
        db.ForeignKey("custom_domain.id", ondelete="cascade"), nullable=True
    )

    user = db.relationship(User)

    @classmethod
    def create_new(cls, user_id, prefix):
        if not prefix:
            raise Exception("alias prefix cannot be empty")

        # find the right suffix - avoid infinite loop by running this at max 1000 times
        for i in range(1000):
            suffix = random_word()
            email = f"{prefix}.{suffix}@{EMAIL_DOMAIN}"

            if not cls.get_by(email=email):
                break

        return GenEmail.create(user_id=user_id, email=email)

    @classmethod
    def create_new_random(cls, user_id, scheme: int = 1, in_hex: bool = False):
        """create a new random alias"""
        random_email = generate_email(scheme=scheme, in_hex=in_hex)
        return GenEmail.create(user_id=user_id, email=random_email)

    def __repr__(self):
        return f"<GenEmail {self.id} {self.email}>"


class ClientUser(db.Model, ModelMixin):
    __table_args__ = (
        db.UniqueConstraint("user_id", "client_id", name="uq_client_user"),
    )

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    client_id = db.Column(db.ForeignKey(Client.id, ondelete="cascade"), nullable=False)

    # Null means client has access to user original email
    gen_email_id = db.Column(
        db.ForeignKey(GenEmail.id, ondelete="cascade"), nullable=True
    )

    # user can decide to send to client another name
    name = db.Column(
        db.String(128), nullable=True, default=None, server_default=text("NULL")
    )

    # user can decide to send to client a default avatar
    default_avatar = db.Column(
        db.Boolean, nullable=False, default=False, server_default="0"
    )

    gen_email = db.relationship(GenEmail, backref="client_users")

    user = db.relationship(User)
    client = db.relationship(Client)

    def get_email(self):
        return self.gen_email.email if self.gen_email_id else self.user.email

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
                if self.gen_email_id:
                    LOG.debug(
                        "Use gen email for user %s, client %s", self.user, self.client
                    )
                    res[Scope.EMAIL.value] = self.gen_email.email
                # Use user original email
                else:
                    res[Scope.EMAIL.value] = self.user.email

        return res


class ForwardEmail(db.Model, ModelMixin):
    """
    Emails that are forwarded through SL: email that is sent by website to user via SL alias
    """

    __table_args__ = (
        db.UniqueConstraint("gen_email_id", "website_email", name="uq_forward_email"),
    )

    gen_email_id = db.Column(
        db.ForeignKey(GenEmail.id, ondelete="cascade"), nullable=False
    )

    # used to be envelope header, should be mail header from instead
    website_email = db.Column(db.String(128), nullable=False)

    # the email from header, e.g. AB CD <ab@cd.com>
    # nullable as this field is added after website_email
    website_from = db.Column(db.String(128), nullable=True)

    # when user clicks on "reply", they will reply to this address.
    # This address allows to hide user personal email
    # this reply email is created every time a website sends an email to user
    # it has the prefix "reply+" to distinguish with other email
    reply_email = db.Column(db.String(128), nullable=False)

    gen_email = db.relationship(GenEmail, backref="forward_emails")

    def website_send_to(self):
        """return the email address with name.
        to use when user wants to send an email from the alias"""
        if self.website_from:
            name = get_email_name(self.website_from)
            if name:
                return name + " " + self.website_email + f" <{self.reply_email}>"

        return self.website_email.replace("@", " at ") + f" <{self.reply_email}>"

    def last_reply(self) -> "ForwardEmailLog":
        """return the most recent reply"""
        return (
            ForwardEmailLog.query.filter_by(forward_id=self.id, is_reply=True)
                .order_by(desc(ForwardEmailLog.created_at))
                .first()
        )


class ForwardEmailLog(db.Model, ModelMixin):
    forward_id = db.Column(
        db.ForeignKey(ForwardEmail.id, ondelete="cascade"), nullable=False
    )

    # whether this is a reply
    is_reply = db.Column(db.Boolean, nullable=False, default=False)

    # for ex if alias is disabled, this forwarding is blocked
    blocked = db.Column(db.Boolean, nullable=False, default=False)


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


class DeletedAlias(db.Model, ModelMixin):
    """Store all deleted alias to make sure they are NOT reused"""

    user_id = db.Column(db.ForeignKey(User.id, ondelete="cascade"), nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)


class EmailChange(db.Model, ModelMixin):
    """Used when user wants to update their email"""

    user_id = db.Column(
        db.ForeignKey(User.id, ondelete="cascade"),
        nullable=False,
        unique=True,
        index=True,
    )
    new_email = db.Column(db.String(128), unique=True, nullable=False)
    code = db.Column(db.String(128), unique=True, nullable=False)
    expired = db.Column(ArrowType, nullable=False, default=_expiration_12h)

    user = db.relationship(User)

    def is_expired(self):
        return self.expired < arrow.now()


class AliasUsedOn(db.Model, ModelMixin):
    """Used to know where an alias is created"""

    __table_args__ = (
        db.UniqueConstraint("gen_email_id", "hostname", name="uq_alias_used"),
    )

    gen_email_id = db.Column(
        db.ForeignKey(GenEmail.id, ondelete="cascade"), nullable=False
    )

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

    def nb_alias(self):
        return GenEmail.filter_by(custom_domain_id=self.id).count()
