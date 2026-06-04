import os
from datetime import timedelta

import arrow
import click
import flask_limiter
import flask_profiler
import newrelic.agent
import sentry_sdk
import time
from flask import (
    Flask,
    redirect,
    url_for,
    render_template,
    request,
    jsonify,
    flash,
    session,
    g,
)
from flask_cors import cross_origin, CORS
from flask_login import current_user
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from werkzeug.middleware.proxy_fix import ProxyFix

from app import build_info, config, constants
from app.admin import init_admin
from app.api.base import api_bp
from app.auth.base import auth_bp
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.developer.base import developer_bp
from app.discover.base import discover_bp
from app.extensions import login_manager, limiter
from app.fake_data import fake_data
from app.internal.base import internal_bp
from app.jose_utils import get_jwk_key
from app.log import LOG
from app.models import (
    User,
    EmailLog,
    Contact,
    Newsletter,
    NewsletterUser,
)
from app.monitor.base import monitor_bp
from app.monitor_utils import send_version_event
from app.newsletter_utils import send_newsletter_to_user
from app.oauth.base import oauth_bp
from app.onboarding.base import onboarding_bp
from app.payments.paddle import setup_paddle_callback
from app.phone.base import phone_bp
from app.redis_services import initialize_redis_services
from app.request_utils import generate_request_id
from app.sentry_utils import sentry_before_send

if config.SENTRY_DSN:
    LOG.d("enable sentry")
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        release=f"app@{build_info.SHA1}",
        integrations=[
            FlaskIntegration(),
            SqlalchemyIntegration(),
        ],
        before_send=sentry_before_send,
        traces_sample_rate=config.SENTRY_TRACE_RATE,
    )

# the app is served behind nginx which uses http and not https
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def setup_do_not_track(app):
    @app.route("/dnt")
    def do_not_track():
        return """
        <script src="/static/local-storage-polyfill.js"></script>

        <script>
// Disable Analytics if this script is called

store.set('analytics-ignore', 't');

alert("Analytics disabled");

window.location.href = "/";

</script>
        """


def register_custom_commands(app):
    """
    Adhoc commands run during data migration.
    Registered as flask command, so it can run as:

    > flask {task-name}
    """

    @app.cli.command("fill-up-email-log-alias")
    def fill_up_email_log_alias():
        """Fill up email_log.alias_id column"""
        # split all emails logs into 1000-size trunks
        nb_email_log = EmailLog.count()
        LOG.d("total trunks %s", nb_email_log // 1000 + 2)
        for trunk in reversed(range(1, nb_email_log // 1000 + 2)):
            nb_update = 0
            for email_log, contact in (
                Session.query(EmailLog, Contact)
                .filter(EmailLog.contact_id == Contact.id)
                .filter(EmailLog.id <= trunk * 1000)
                .filter(EmailLog.id > (trunk - 1) * 1000)
                .filter(EmailLog.alias_id.is_(None))
            ):
                email_log.alias_id = contact.alias_id
                nb_update += 1

            LOG.d("finish trunk %s, update %s email logs", trunk, nb_update)
            Session.commit()

    @app.cli.command("dummy-data")
    def dummy_data():
        from init_app import add_sl_domains, add_proton_partner
        from app.rate_limiter import set_rate_limit_enabled

        set_rate_limit_enabled(False)
        LOG.w("reset db, add fake data")
        add_proton_partner()
        fake_data()
        add_sl_domains()

    @app.cli.command("send-newsletter")
    @click.option("-n", "--newsletter_id", type=int, help="Newsletter ID to be sent")
    def send_newsletter(newsletter_id):
        newsletter = Newsletter.get(newsletter_id)
        if not newsletter:
            LOG.w(f"no such newsletter {newsletter_id}")
            return

        nb_success = 0
        nb_failure = 0

        # user_ids that have received the newsletter
        user_received_newsletter = Session.query(NewsletterUser.user_id).filter(
            NewsletterUser.newsletter_id == newsletter_id
        )

        # only send newsletter to those who haven't received it
        # not query users directly here as we can run out of memory
        user_ids = (
            Session.query(User.id)
            .order_by(User.id)
            .filter(User.id.notin_(user_received_newsletter))
            .all()
        )

        # user_ids is an array of tuple (user_id,)
        user_ids = [user_id[0] for user_id in user_ids]

        for user_id in user_ids:
            user = User.get(user_id)
            # refetch newsletter
            newsletter = Newsletter.get(newsletter_id)

            if not user:
                LOG.i(f"User {user_id} was maybe deleted in the meantime")
                continue

            comm_email, unsubscribe_link, via_email = user.get_communication_email()
            if not comm_email:
                continue

            sent, error_msg = send_newsletter_to_user(newsletter, user)
            if sent:
                LOG.d(f"{newsletter} sent to {user}")
                nb_success += 1
            else:
                nb_failure += 1

            # sleep in between to not overwhelm mailbox provider
            time.sleep(0.2)

        LOG.d(f"Nb success {nb_success}, failures {nb_failure}")


@login_manager.user_loader
def load_user(alternative_id):
    user = User.get_by(alternative_id=alternative_id)
    if user:
        sentry_sdk.set_user({"email": user.email, "id": user.id})
        if user.disabled:
            return None
        if not user.is_active():
            return None

    return user


def register_blueprints(app: Flask):
    app.register_blueprint(auth_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(developer_bp)
    app.register_blueprint(phone_bp)

    app.register_blueprint(oauth_bp, url_prefix="/oauth")
    app.register_blueprint(oauth_bp, url_prefix="/oauth2")
    app.register_blueprint(onboarding_bp)

    app.register_blueprint(discover_bp)
    app.register_blueprint(internal_bp)
    app.register_blueprint(api_bp)


def set_index_page(app):
    @app.route("/", methods=["GET", "POST"])
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        else:
            return redirect(url_for("auth.login"))

    @app.before_request
    def before_request():
        # not logging /static call
        if (
            not request.path.startswith("/static")
            and not request.path.startswith("/admin/static")
            and not request.path.startswith("/_debug_toolbar")
        ):
            g.start_time = time.time()
            g.request_id = generate_request_id()

            # to handle the referral url that has ?slref=code part
            ref_code = request.args.get("slref")
            if ref_code:
                session["slref"] = ref_code

    @app.after_request
    def after_request(res):
        # not logging /static call
        if (
            not request.path.startswith("/static")
            and not request.path.startswith("/admin/static")
            and not request.path.startswith("/_debug_toolbar")
            and not request.path.startswith("/git")
            and not request.path.startswith("/favicon.ico")
            and not request.path.startswith("/health")
        ):
            start_time = g.start_time or time.time()
            LOG.d(
                "%s %s %s %s %s, takes %s",
                request.remote_addr,
                request.method,
                request.path,
                request.args,
                res.status_code,
                time.time() - start_time,
            )
            newrelic.agent.record_custom_event(
                "HttpResponseStatus", {"code": res.status_code}
            )
            send_version_event("app")
        return res


def setup_openid_metadata(app):
    @app.route("/.well-known/openid-configuration")
    @cross_origin()
    def openid_config():
        res = {
            "issuer": config.URL,
            "authorization_endpoint": config.URL + "/oauth2/authorize",
            "token_endpoint": config.URL + "/oauth2/token",
            "userinfo_endpoint": config.URL + "/oauth2/userinfo",
            "jwks_uri": config.URL + "/jwks",
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
            # "introspection_endpoint": URL + "/oauth2/token/introspection",
            # "revocation_endpoint": URL + "/oauth2/token/revocation",
        }

        return jsonify(res)

    @app.route("/jwks")
    @cross_origin()
    def jwks():
        res = {"keys": [get_jwk_key()]}
        return jsonify(res)


def get_current_user():
    try:
        return g.user
    except AttributeError:
        return current_user


def setup_error_page(app):
    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Bad Request"), 400
        else:
            return render_template("error/400.html"), 400

    @app.errorhandler(401)
    def unauthorized(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Unauthorized"), 401
        else:
            flash("You need to login to see this page", "error")
            return redirect(url_for("auth.login", next=request.full_path))

    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Forbidden"), 403
        else:
            return render_template("error/403.html"), 403

    @app.errorhandler(429)
    def rate_limited(e):
        LOG.w(
            "Client hit rate limit on path %s, user:%s",
            request.path,
            get_current_user(),
        )
        if request.path.startswith("/api/"):
            return jsonify(error="Rate limit exceeded"), 429
        else:
            return render_template("error/429.html"), 429

    @app.errorhandler(404)
    def page_not_found(e):
        if request.path.startswith("/api/"):
            return jsonify(error="No such endpoint"), 404
        else:
            return render_template("error/404.html"), 404

    @app.errorhandler(405)
    def wrong_method(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Method not allowed"), 405
        else:
            return render_template("error/405.html"), 405

    @app.errorhandler(Exception)
    def error_handler(e):
        LOG.e(e)
        if request.path.startswith("/api/"):
            return jsonify(error="Internal error"), 500
        else:
            return render_template("error/500.html"), 500


def setup_favicon_route(app):
    @app.route("/favicon.ico")
    def favicon():
        return redirect("/static/favicon.ico")


def jinja2_filter(app):
    def format_datetime(value):
        dt = arrow.get(value)
        return dt.humanize()

    def iterable_enumerate(iterable):
        return enumerate(iterable)

    app.jinja_env.filters["dt"] = format_datetime
    app.jinja_env.filters["enumerate"] = iterable_enumerate

    @app.context_processor
    def inject_stage_and_region():
        now = arrow.now()
        return dict(
            YEAR=now.year,
            NOW=now,
            URL=config.URL,
            SENTRY_DSN=config.SENTRY_FRONT_END_DSN,
            VERSION=build_info.SHA1,
            FIRST_ALIAS_DOMAIN=config.FIRST_ALIAS_DOMAIN,
            PLAUSIBLE_HOST=config.PLAUSIBLE_HOST,
            PLAUSIBLE_DOMAIN=config.PLAUSIBLE_DOMAIN,
            GITHUB_CLIENT_ID=config.GITHUB_CLIENT_ID,
            GOOGLE_CLIENT_ID=config.GOOGLE_CLIENT_ID,
            FACEBOOK_CLIENT_ID=config.FACEBOOK_CLIENT_ID,
            LANDING_PAGE_URL=config.LANDING_PAGE_URL,
            STATUS_PAGE_URL=config.STATUS_PAGE_URL,
            SUPPORT_EMAIL=config.SUPPORT_EMAIL,
            PGP_SIGNER=config.PGP_SIGNER,
            CANONICAL_URL=f"{config.URL}{request.path}",
            PAGE_LIMIT=config.PAGE_LIMIT,
            ZENDESK_ENABLED=config.ZENDESK_ENABLED,
            MAX_NB_EMAIL_FREE_PLAN=config.MAX_NB_EMAIL_FREE_PLAN,
            HEADER_ALLOW_API_COOKIES=constants.HEADER_ALLOW_API_COOKIES,
        )


def init_extensions(app: Flask):
    login_manager.init_app(app)


def create_simplelogin_app():
    app = Flask(__name__)
    # SimpleLogin is deployed behind NGINX
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

    app.url_map.strict_slashes = False

    app.config["SQLALCHEMY_DATABASE_URI"] = config.DB_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # enable to print all queries generated by sqlalchemy
    # app.config["SQLALCHEMY_ECHO"] = True

    app.secret_key = config.FLASK_SECRET

    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # to have a "fluid" layout for admin
    app.config["FLASK_ADMIN_FLUID_LAYOUT"] = True

    # to avoid conflict with other cookie
    app.config["SESSION_COOKIE_NAME"] = config.SESSION_COOKIE_NAME
    if config.URL.startswith("https"):
        app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if config.MEM_STORE_URI:
        app.config[flask_limiter.extension.C.STORAGE_URL] = config.MEM_STORE_URI
        initialize_redis_services(app, config.MEM_STORE_URI)

    limiter.init_app(app)

    setup_error_page(app)

    init_extensions(app)
    register_blueprints(app)
    set_index_page(app)
    jinja2_filter(app)

    setup_favicon_route(app)
    setup_openid_metadata(app)

    init_admin(app)
    setup_paddle_callback(app)
    setup_do_not_track(app)
    register_custom_commands(app)

    if config.FLASK_PROFILER_PATH:
        LOG.d("Enable flask-profiler")
        app.config["flask_profiler"] = {
            "enabled": True,
            "storage": {"engine": "sqlite", "FILE": config.FLASK_PROFILER_PATH},
            "basicAuth": {
                "enabled": True,
                "username": "admin",
                "password": config.FLASK_PROFILER_PASSWORD,
            },
            "ignore": ["^/static/.*", "/git", "/exception", "/health"],
        }
        flask_profiler.init_app(app)

    # enable CORS on /api endpoints
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    @app.before_request
    def check_maintenance_mode():
        if not config.MAINTENANCE_MODE:
            return
        # Allow health checks, admin access, and static assets during maintenance
        if (
            request.path.startswith("/health")
            or request.path.startswith("/admin")
            or request.path.startswith("/static")
        ):
            return
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {"error": "Service is under maintenance, please try again later"}
                ),
                503,
            )
        return render_template("error/503.html"), 503

    # set session to permanent so user stays signed in after quitting the browser
    # the cookie is valid for 7 days
    @app.before_request
    def make_session_permanent():
        session.permanent = True
        app.permanent_session_lifetime = timedelta(days=7)

    @app.teardown_appcontext
    def cleanup(resp_or_exc):
        Session.remove()

    @app.route("/health", methods=["GET"])
    def healthcheck():
        return "success", 200

    return app
