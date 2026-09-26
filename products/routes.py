"""
products/routes.py — Product CRUD.

R04 — SEEDED BUG: Product prices must never be negative.
      BUG: There is NO price validation here. A product with price=-1 (or any
      negative value) will be accepted and stored with HTTP 201.
      A correct implementation would return HTTP 400 for price < 0.
"""
from flask import Blueprint, request, jsonify

products_bp = Blueprint("products", __name__)


def _require_auth(admin_only=False):
    """Helper: validate bearer token from Authorization header.

    Returns (user_id, role) on success, or (None, None) if invalid/missing.
    """
    from app import auth_tokens
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, None
    token_str = auth_header[len("Bearer "):]
    entry = auth_tokens.get(token_str)
    if not entry:
        return None, None
    if admin_only and entry["role"] != "admin":
        return None, None
    return entry["user_id"], entry["role"]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@products_bp.route("", methods=["GET"])
def list_products():
    """GET /products — return all products."""
    from app import products
    return jsonify(list(products.values())), 200


@products_bp.route("/<int:product_id>", methods=["GET"])
def get_product(product_id: int):
    """GET /products/<id> — return a single product."""
    from app import products
    product = products.get(product_id)
    if not product:
        return jsonify(error="product not found"), 404
    return jsonify(product), 200


@products_bp.route("", methods=["POST"])
def create_product():
    """
    POST /products — create a new product.

    ⚠ R04 SEEDED BUG: price is stored as-is with NO validation.
    A negative price such as -10 is accepted and returns HTTP 201.
    """
    from app import products, next_id
    data = request.get_json(silent=True) or {}
    name  = data.get("name", "").strip()
    price = data.get("price")

    if not name or price is None:
        return jsonify(error="name and price are required"), 400

    # ── BUG (R04): missing validation ─────────────────────────────────────────
    # A correct implementation would have:
    #   if price < 0:
    #       return jsonify(error="price must not be negative"), 400
    # That check is intentionally absent here.
    # ──────────────────────────────────────────────────────────────────────────

    product_id = next_id("product")
    product = {"id": product_id, "name": name, "price": price}
    products[product_id] = product
    return jsonify(product), 201


@products_bp.route("/<int:product_id>", methods=["PUT"])
def update_product(product_id: int):
    """PUT /products/<id> — update name and/or price."""
    from app import products
    product = products.get(product_id)
    if not product:
        return jsonify(error="product not found"), 404

    data = request.get_json(silent=True) or {}
    if "name" in data:
        product["name"] = data["name"]
    if "price" in data:
        product["price"] = data["price"]
    return jsonify(product), 200


@products_bp.route("/<int:product_id>", methods=["DELETE"])
def delete_product(product_id: int):
    """
    DELETE /products/<id> — remove the product.

    ⚠ R08 SEEDED BUG: cart items referencing this product are NOT deleted.
    A correct implementation would iterate carts and remove matching items.
    That cascade is intentionally absent here.
    """
    from app import products
    # ── BUG (R08): no cascade delete of cart items ─────────────────────────────
    # A correct implementation would have:
    #   for user_id in carts:
    #       carts[user_id] = [i for i in carts[user_id] if i["product_id"] != product_id]
    # That cleanup is intentionally absent here.
    # ──────────────────────────────────────────────────────────────────────────
    if product_id not in products:
        return jsonify(error="product not found"), 404
    del products[product_id]
    return jsonify(message="deleted"), 200
