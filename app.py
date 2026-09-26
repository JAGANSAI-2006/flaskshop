"""
FlaskShop — minimal Python/Flask e-commerce API (demo for Requirement-to-Code Verifier).

In-memory storage (no database):
  users    : user_id -> {id, username, email, password_hash, role}
  tokens   : token_str -> {user_id, expires_in, created_at}
  products : product_id -> {id, name, price}
  carts    : user_id  -> [{product_id, quantity}]
  orders   : user_id  -> [{id, items, total, created_at}]
"""
from flask import Flask, jsonify

# ── Shared in-memory stores ────────────────────────────────────────────────────
users = {}       # user_id   -> user dict
reset_tokens = {}  # token_str -> token dict
products = {}    # product_id -> product dict
carts = {}       # user_id   -> list of {product_id, quantity}
orders = {}      # user_id   -> list of order dicts

# ── Simple token-based auth store (token_str -> {user_id, role}) ──────────────
auth_tokens = {}  # issued by /auth/login

_next_id = {"user": 1, "product": 1, "order": 1}


def next_id(kind: str) -> int:
    val = _next_id[kind]
    _next_id[kind] += 1
    return val


def create_app():
    app = Flask(__name__)

    # ── Register blueprints ────────────────────────────────────────────────────
    from auth.tokens import tokens_bp
    from auth.users import users_bp
    from auth.login import login_bp
    from products.routes import products_bp
    from cart.routes import cart_bp
    from orders.routes import orders_bp
    from admin.routes import admin_bp
    from search.routes import search_bp

    app.register_blueprint(tokens_bp,   url_prefix="/auth")
    app.register_blueprint(users_bp,    url_prefix="/auth")
    app.register_blueprint(login_bp,    url_prefix="/auth")
    app.register_blueprint(products_bp, url_prefix="/products")
    app.register_blueprint(cart_bp,     url_prefix="/cart")
    app.register_blueprint(orders_bp,   url_prefix="/orders")
    app.register_blueprint(admin_bp,    url_prefix="/admin")
    app.register_blueprint(search_bp,   url_prefix="/search")

    # ── R12: all error pages return JSON, never HTML ───────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error="Bad Request", message=str(e)), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify(error="Unauthorized", message=str(e)), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify(error="Forbidden", message=str(e)), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error="Not Found", message=str(e)), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify(error="Method Not Allowed", message=str(e)), 405

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify(error="Internal Server Error", message=str(e)), 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
