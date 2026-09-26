"""
cart/routes.py — Cart management.

R03: A user must not be able to place an order with an empty cart.
     POST /cart/checkout returns HTTP 400 when the cart is empty.

R07: The cart total must correctly apply percentage discount codes.
     Discount codes are stored in DISCOUNT_CODES dict. A 10% code reduces the
     total by 10%.

R08 — SEEDED BUG: Deleting a product must also delete all associated cart items.
      The actual cascade is in products/routes.py DELETE handler — which is
      intentionally absent. Cart items referencing a deleted product remain here.
"""
from flask import Blueprint, request, jsonify

cart_bp = Blueprint("cart", __name__)

# ── Known discount codes (percentage off) ─────────────────────────────────────
DISCOUNT_CODES = {
    "SAVE10": 10,
    "SAVE20": 20,
    "HALFOFF": 50,
}


def _get_user_id_from_token():
    """Extract user_id from bearer token; return None if missing/invalid."""
    from app import auth_tokens
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token_str = auth_header[len("Bearer "):]
    entry = auth_tokens.get(token_str)
    return entry["user_id"] if entry else None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@cart_bp.route("", methods=["GET"])
def get_cart():
    """GET /cart — return the current user's cart items."""
    from app import carts
    user_id = _get_user_id_from_token()
    if not user_id:
        return jsonify(error="Unauthorized"), 401
    items = carts.get(user_id, [])
    return jsonify(items=items), 200


@cart_bp.route("/items", methods=["POST"])
def add_to_cart():
    """POST /cart/items — add a product to the cart.

    Body: {product_id, quantity}
    """
    from app import carts, products
    user_id = _get_user_id_from_token()
    if not user_id:
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    quantity   = data.get("quantity", 1)

    if product_id not in products:
        return jsonify(error="product not found"), 404

    cart = carts.setdefault(user_id, [])
    # Merge with existing entry if present
    for item in cart:
        if item["product_id"] == product_id:
            item["quantity"] += quantity
            return jsonify(cart=cart), 200

    cart.append({"product_id": product_id, "quantity": quantity})
    return jsonify(cart=cart), 201


@cart_bp.route("/items/<int:product_id>", methods=["DELETE"])
def remove_from_cart(product_id: int):
    """DELETE /cart/items/<product_id> — remove a specific product from the cart."""
    from app import carts
    user_id = _get_user_id_from_token()
    if not user_id:
        return jsonify(error="Unauthorized"), 401

    cart = carts.get(user_id, [])
    new_cart = [i for i in cart if i["product_id"] != product_id]
    carts[user_id] = new_cart
    return jsonify(cart=new_cart), 200


@cart_bp.route("/total", methods=["GET"])
def cart_total():
    """
    GET /cart/total?discount_code=SAVE10

    R07: Applies the percentage discount correctly.
    total = sum(product.price * qty for each item)
    discounted_total = total * (1 - discount_pct / 100)
    """
    from app import carts, products
    user_id = _get_user_id_from_token()
    if not user_id:
        return jsonify(error="Unauthorized"), 401

    cart = carts.get(user_id, [])
    discount_code = request.args.get("discount_code", "").upper()

    # Compute raw total
    total = 0.0
    for item in cart:
        product = products.get(item["product_id"])
        if product:
            total += product["price"] * item["quantity"]

    # R07: apply discount
    discount_pct = DISCOUNT_CODES.get(discount_code, 0)
    discounted_total = round(total * (1 - discount_pct / 100), 2)

    return jsonify(
        subtotal=round(total, 2),
        discount_code=discount_code or None,
        discount_percent=discount_pct,
        total=discounted_total,
    ), 200


@cart_bp.route("/checkout", methods=["POST"])
def checkout():
    """
    POST /cart/checkout — place an order from the current cart.

    R03: Returns HTTP 400 if the cart is empty.
    """
    from app import carts, orders, products, next_id
    import time

    user_id = _get_user_id_from_token()
    if not user_id:
        return jsonify(error="Unauthorized"), 401

    cart = carts.get(user_id, [])

    # R03: guard against empty cart
    if not cart:
        return jsonify(error="Cannot place an order with an empty cart"), 400

    # Build order
    total = 0.0
    order_items = []
    for item in cart:
        product = products.get(item["product_id"])
        if product:
            line_total = product["price"] * item["quantity"]
            total += line_total
            order_items.append({
                "product_id":   item["product_id"],
                "product_name": product["name"],
                "quantity":     item["quantity"],
                "unit_price":   product["price"],
                "line_total":   round(line_total, 2),
            })

    order = {
        "id":         next_id("order"),
        "user_id":    user_id,
        "items":      order_items,
        "total":      round(total, 2),
        "created_at": time.time(),
    }

    if user_id not in orders:
        orders[user_id] = []
    orders[user_id].append(order)

    # Clear cart after successful checkout
    carts[user_id] = []

    return jsonify(order), 201
