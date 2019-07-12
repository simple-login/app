import os
import ssl

import arrow
import sentry_sdk
import stripe
from flask import Flask, redirect, url_for, render_template, request, jsonify
from flask_admin import Admin
from flask_cors import cross_origin
from flask_debugtoolbar import DebugToolbarExtension
from flask_login import current_user
from sentry_sdk.integrations.flask import FlaskIntegration

from app.admin_model import SLModelView, SLAdminIndexView
from app.auth.base import auth_bp
from app.config import (
    DB_URI,
    FLASK_SECRET,
    ENABLE_SENTRY,
    ENV,
    URL,
    SHA1,
    LYRA_ANALYTICS_ID,
    STRIPE_SECRET_KEY,
)
from app.dashboard.base import dashboard_bp
from app.developer.base import developer_bp
from app.discover.base import discover_bp
from app.extensions import db, login_manager, migrate
from app.jose_utils import get_jwk_key
from app.log import LOG
from app.models import Client, User, ClientUser, GenEmail, RedirectUri, Partner
from app.monitor.base import monitor_bp
from app.oauth.base import oauth_bp
from app.partner.base import partner_bp

if ENABLE_SENTRY:
    LOG.d("enable sentry")
    sentry_sdk.init(
        dsn="https://ad2187ed843340a1b4165bd8d5d6cdce@sentry.io/1478143",
        integrations=[FlaskIntegration()],
    )

# the app is served behin nginx which uses http and not https
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.config["SQLALCHEMY_DATABASE_URI"] = DB_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = FLASK_SECRET

    app.config["TEMPLATES_AUTO_RELOAD"] = True

    init_extensions(app)
    register_blueprints(app)
    set_index_page(app)
    jinja2_filter(app)

    setup_error_page(app)

    setup_favicon_route(app)
    setup_openid_metadata(app)

    stripe.api_key = STRIPE_SECRET_KEY

    init_admin(app)

    return app


def fake_data():
    LOG.d("create fake data")
    # Remove db if exist
    if os.path.exists("db.sqlite"):
        LOG.d("remove existing db file")
        os.remove("db.sqlite")

    # Create all tables
    db.create_all()

    # Create a user
    user = User.create(
        email="nguyenkims+local@gmail.com",
        name="Son Local",
        password="password",
        activated=True,
        is_admin=True,
        is_developer=True,
    )

    db.session.commit()

    GenEmail.create_new_gen_email(user_id=user.id)

    # Create a client
    client1 = Client.create_new(name="Demo", user_id=user.id)
    client1.home_url = "http://sl-client:7000"
    client1.oauth_client_id = "client-id"
    client1.oauth_client_secret = "client-secret"
    client1.published = True
    db.session.commit()

    RedirectUri.create(client_id=client1.id, uri="http://sl-client:7000/callback")
    RedirectUri.create(client_id=client1.id, uri="http://sl-client:7000/implicit")
    RedirectUri.create(client_id=client1.id, uri="http://sl-client:7000/implicit-jso")
    db.session.commit()


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(user_id)

    return user


def register_blueprints(app: Flask):
    app.register_blueprint(auth_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(developer_bp)
    app.register_blueprint(partner_bp)

    app.register_blueprint(oauth_bp, url_prefix="/oauth")
    app.register_blueprint(oauth_bp, url_prefix="/oauth2")

    app.register_blueprint(discover_bp)


def set_index_page(app):
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        else:
            return redirect(url_for("auth.login"))

    @app.after_request
    def after_request(res):
        # not logging /static call
        if (
            not request.path.startswith("/static")
            and not request.path.startswith("/admin/static")
            and not request.path.startswith("/_debug_toolbar")
        ):
            LOG.debug(
                "%s %s %s %s %s",
                request.remote_addr,
                request.method,
                request.path,
                request.args,
                res.status_code,
            )
        return res


def setup_openid_metadata(app):
    @app.route("/.well-known/openid-configuration")
    @cross_origin()
    def openid_config():
        res = {
            "issuer": URL,
            "authorization_endpoint": URL + "/oauth2/authorize",
            "token_endpoint": URL + "/oauth2/token",
            "jwks_uri": URL + "/jwks",
            "response_types_supported": [
                "code",
                "token",
                "id_token",
                "id_token token",
                "id_token code",
            ],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            # todo: add introspection and revocation endpoints
            "introspection_endpoint": URL + "/oauth2/token/introspection",
            "revocation_endpoint": URL + "/oauth2/token/revocation",
        }

        return jsonify(res)

    @app.route("/jwks")
    @cross_origin()
    def jwks():
        res = {"keys": [get_jwk_key()]}
        return jsonify(res)


def setup_error_page(app):
    @app.errorhandler(400)
    def page_not_found(e):
        return render_template("error/400.html"), 400

    @app.errorhandler(401)
    def page_not_found(e):
        return render_template("error/401.html", current_url=request.full_path), 401

    @app.errorhandler(403)
    def page_not_found(e):
        return render_template("error/403.html"), 403

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("error/404.html"), 404

    @app.errorhandler(Exception)
    def error_handler(e):
        LOG.exception(e)
        return render_template("error/500.html"), 500


def setup_favicon_route(app):
    @app.route("/favicon.ico")
    def favicon():
        return redirect("/static/favicon.ico")


def jinja2_filter(app):
    def format_datetime(value):
        dt = arrow.get(value)
        return dt.humanize()

    app.jinja_env.filters["dt"] = format_datetime

    @app.context_processor
    def inject_stage_and_region():
        return dict(
            YEAR=arrow.now().year,
            URL=URL,
            ENABLE_SENTRY=ENABLE_SENTRY,
            VERSION=SHA1,
            LYRA_ANALYTICS_ID=LYRA_ANALYTICS_ID,
        )


def init_extensions(app: Flask):
    LOG.debug("init extensions")
    login_manager.init_app(app)
    db.init_app(app)
    migrate.init_app(app)


def init_admin(app):
    admin = Admin(name="SimpleLogin", template_mode="bootstrap3")

    admin.init_app(app, index_view=SLAdminIndexView())
    admin.add_view(SLModelView(User, db.session))
    admin.add_view(SLModelView(Client, db.session))
    admin.add_view(SLModelView(GenEmail, db.session))
    admin.add_view(SLModelView(ClientUser, db.session))
    admin.add_view(SLModelView(Partner, db.session, endpoint="admin-partner"))


if __name__ == "__main__":
    app = create_app()

    # enable flask toolbar
    # the toolbar is only enabled in debug mode:
    app.debug = True

    app.config["DEBUG_TB_PROFILER_ENABLED"] = True
    app.config["DEBUG_TB_INTERCEPT_REDIRECTS"] = False

    toolbar = DebugToolbarExtension(app)

    # enable to print all queries generated by sqlalchemy
    # app.config["SQLALCHEMY_ECHO"] = True

    if ENV == "local":
        LOG.d("reset db, add fake data")
        with app.app_context():
            fake_data()

    if URL.startswith("https"):
        LOG.d("enable https")
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        context.load_cert_chain("local_data/cert.pem", "local_data/key.pem")

        app.run(debug=True, host="0.0.0.0", port=7777, ssl_context=context)
    else:
        app.run(debug=True, host="0.0.0.0", port=7777)
