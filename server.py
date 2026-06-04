import os
from flask import Flask

from app import config
from app.db import Session

# the app is served behind nginx which uses http and not https
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def create_light_app() -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = config.DB_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    @app.teardown_appcontext
    def shutdown_session(response_or_exc):
        Session.remove()

    return app


def create_app() -> Flask:
    if config.MAINTENANCE_MODE:
        from maintenance_app import create_maintenance_app

        return create_maintenance_app()
    else:
        from simplelogin_app import create_simplelogin_app

        return create_simplelogin_app()


def local_main():
    config.COLOR_LOG = True
    app = create_app()

    if not config.MAINTENANCE_MODE:
        # enable flask toolbar
        from flask_debugtoolbar import DebugToolbarExtension

        # Disabled in python 3.12 as it collides with the default CPython profiler
        app.config["DEBUG_TB_PROFILER_ENABLED"] = False
        app.config["DEBUG_TB_INTERCEPT_REDIRECTS"] = False
        app.debug = True
        DebugToolbarExtension(app)

        # disable the sqlalchemy debug panels because of "IndexError: pop from empty list" from:
        # duration = time.time() - conn.info['query_start_time'].pop(-1)
        # app.config["DEBUG_TB_PANELS"] += ("flask_debugtoolbar_sqlalchemy.SQLAlchemyPanel",)

    app.run(debug=True, port=7777)

    # uncomment to run https locally
    # LOG.d("enable https")
    # import ssl
    # context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    # context.load_cert_chain("local_data/cert.pem", "local_data/key.pem")
    # app.run(debug=True, port=7777, ssl_context=context)


if __name__ == "__main__":
    local_main()
