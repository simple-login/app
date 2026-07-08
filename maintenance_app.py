from app import config

from flask import Flask, request, jsonify, render_template
from werkzeug.middleware.proxy_fix import ProxyFix


def create_maintenance_app() -> Flask:
    """Minimal Flask app used when MAINTENANCE_MODE is set at startup.
    Requires no database connection."""
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

    @app.route("/health", methods=["GET"])
    def healthcheck():
        return "success", 200

    @app.before_request
    def maintenance():
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

    @app.context_processor
    def inject_stage_and_region():
        import arrow

        now = arrow.now()
        return dict(
            YEAR=now.year,
            NOW=now,
            URL=config.URL,
        )

    return app
