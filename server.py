import os

from flask import Flask

from app.auth.base import auth_bp
from app.dashboard.base import dashboard_bp
from app.extensions import db, login_manager
from app.log import LOG
from app.models import Client, User
from app.monitor.base import monitor_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.sqlite"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = "secret"

    app.config["TEMPLATES_AUTO_RELOAD"] = True

    init_extensions(app)
    register_blueprints(app)

    return app


def fake_data():
    # Remove db if exist
    if os.path.exists("db.sqlite"):
        os.remove("db.sqlite")

    db.create_all()

    # fake data
    client = Client(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:7000/callback",
        name="Continental",
    )
    db.session.add(client)

    user = User(id=1, email="john@wick.com", name="John Wick")
    user.set_password("password")
    db.session.add(user)

    db.session.commit()


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(user_id)

    return user


def register_blueprints(app: Flask):
    app.register_blueprint(auth_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(dashboard_bp)


def init_extensions(app: Flask):
    LOG.debug("init extensions")
    login_manager.init_app(app)
    db.init_app(app)


if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        fake_data()

    app.run(debug=True, threaded=False)
