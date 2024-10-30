from flask import Blueprint, jsonify

bp = Blueprint("status", __name__)


@bp.route("/status")
def status():
    return jsonify({"success": True})


@bp.route("/ping")
def ping():
    return jsonify({"success": True})
