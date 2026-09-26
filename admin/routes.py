"""
admin/routes.py — Admin panel endpoints.

R05 — SEEDED BUG: Admin endpoints must require an admin role; regular users must
      receive HTTP 403.
      BUG: There is NO authentication decorator or role check on ANY route here.
      Any request — authenticated or not, any role — receives HTTP 200.
      A correct implementation would check the bearer token for role == "admin"
      and return 403 otherwise.
"""
from flask import Blueprint, jsonify

admin_bp = Blueprint("admin", __name__)

# ── Endpoints — NO auth check (R05 BUG) ───────────────────────────────────────
# A correct implementation would decorate each route with something like:
#
#   def require_admin(f):
#       @wraps(f)
#       def decorated(*args, **kwargs):
#           user_id, role = _get_token_info()
#           if role != "admin":
#               return jsonify(error="Forbidden"), 403
#           return f(*args, **kwargs)
#       return decorated
#
# That decorator is intentionally absent below.


@admin_bp.route("/users", methods=["GET"])
def admin_list_users():
    """
    GET /admin/users — list all registered users.

    ⚠ R05 SEEDED BUG: No auth check. Any caller gets HTTP 200.
    """
    from app import users
    # Return safe view (no password hashes)
    result = [
        {"id": u["id"], "username": u["username"],
         "email": u["email"], "role": u["role"]}
        for u in users.values()
    ]
    return jsonify(users=result), 200


@admin_bp.route("/products", methods=["GET"])
def admin_list_products():
    """
    GET /admin/products — list all products (admin view).

    ⚠ R05 SEEDED BUG: No auth check. Any caller gets HTTP 200.
    """
    from app import products
    return jsonify(products=list(products.values())), 200


@admin_bp.route("/orders", methods=["GET"])
def admin_list_orders():
    """
    GET /admin/orders — list all orders across all users.

    ⚠ R05 SEEDED BUG: No auth check. Any caller gets HTTP 200.
    """
    from app import orders
    all_orders = [order for user_orders in orders.values() for order in user_orders]
    return jsonify(orders=all_orders), 200
