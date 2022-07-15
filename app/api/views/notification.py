from flask import g
from flask import jsonify
from flask import request

from app.api.base import api_bp, require_api_auth
from app.config import PAGE_LIMIT
from app.db import Session
from app.models import Notification


@api_bp.route("/notifications", methods=["GET"])
@require_api_auth
def get_notifications():
    """
    Get notifications

    Input:
    - page: in url. Starts at 0

    Output:
    - more: boolean. Whether there's more notification to load
    - notifications: list of notifications.
        - id
        - message
        - title
        - read
        - created_at
    """
    user = g.user
    try:
        page = int(request.args.get("page"))
    except (ValueError, TypeError):
        return jsonify(error="page must be provided in request query"), 400

    notifications = (
        Notification.filter_by(user_id=user.id)
        .order_by(Notification.read, Notification.created_at.desc())
        .limit(PAGE_LIMIT + 1)  # load a record more to know whether there's more
        .offset(page * PAGE_LIMIT)
        .all()
    )

    have_more = len(notifications) > PAGE_LIMIT

    return (
        jsonify(
            more=have_more,
            notifications=[
                {
                    "id": notification.id,
                    "message": notification.message,
                    "title": notification.title,
                    "read": notification.read,
                    "created_at": notification.created_at.humanize(),
                }
                for notification in notifications[:PAGE_LIMIT]
            ],
        ),
        200,
    )


@api_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@require_api_auth
def mark_as_read(notification_id):
    """
    Mark a notification as read
    Input:
        notification_id: in url
    Output:
        200 if updated successfully

    """
    user = g.user
    notification = Notification.get(notification_id)

    if not notification or notification.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    notification.read = True
    Session.commit()

    return jsonify(done=True), 200
