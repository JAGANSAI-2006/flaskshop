"""
orders/routes.py — Order placement and history.

R10: Order history must be paginated with a maximum of 20 orders per page.
     GET /orders?page=1 returns at most 20 orders per page.
"""
from flask import Blueprint, request, jsonify

orders_bp = Blueprint("orders", __name__)

PAGE_SIZE = 20  # R10: maximum orders per page


def _get_user_id_from_token():
    """Extract user_id from bearer token; return None if missing/invalid."""
    from app import auth_tokens
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token_str = auth_header[len("Bearer "):]
    entry = auth_tokens.get(token_str)
    return entry["user_id"] if entry else None


@orders_bp.route("", methods=["GET"])
def order_history():
    """
    GET /orders?page=<n>

    R10: Returns a paginated list of the authenticated user's orders.
         Maximum of 20 orders per page.
    """
    from app import orders
    user_id = _get_user_id_from_token()
    if not user_id:
        return jsonify(error="Unauthorized"), 401

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    user_orders = orders.get(user_id, [])

    # R10: paginate — slice to at most PAGE_SIZE entries per page
    start = (page - 1) * PAGE_SIZE
    end   = start + PAGE_SIZE
    page_orders = user_orders[start:end]

    return jsonify(
        page=page,
        page_size=PAGE_SIZE,
        total=len(user_orders),
        orders=page_orders,
    ), 200


@orders_bp.route("/<int:order_id>", methods=["GET"])
def get_order(order_id: int):
    """GET /orders/<id> — return a single order belonging to the authenticated user."""
    from app import orders
    user_id = _get_user_id_from_token()
    if not user_id:
        return jsonify(error="Unauthorized"), 401

    for order in orders.get(user_id, []):
        if order["id"] == order_id:
            return jsonify(order), 200

    return jsonify(error="order not found"), 404
