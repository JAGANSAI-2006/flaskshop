"""
smoke_test.py - Confirms all 3 seeded bugs behave as expected.

Uses Flask's built-in test client (no live server required).
Run with:  python smoke_test.py

Expected results
----------------
R04 BUG  POST /products price=-10        -> 201  (should be 400, bug confirmed)
R05 BUG  GET  /admin/users  no token     -> 200  (should be 403, bug confirmed)
R08 BUG  DELETE /products/1 then GET /cart -> deleted product still in cart (bug confirmed)
"""
import json
import sys

from app import create_app, users, products, carts, orders, auth_tokens, reset_tokens, _next_id


# ── Reset all in-memory stores between checks ─────────────────────────────────

def _reset():
    users.clear()
    products.clear()
    carts.clear()
    orders.clear()
    auth_tokens.clear()
    reset_tokens.clear()
    _next_id["user"]    = 1
    _next_id["product"] = 1
    _next_id["order"]   = 1


app = create_app()
client = app.test_client()

results = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    line = "  [{}] {}".format(status, label)
    if detail:
        line += "  ({})".format(detail)
    print(line)
    results.append(condition)


# =============================================================================
# R04 BUG - POST /products with price=-10 must return 201 (no validation)
# =============================================================================
print("\n--- R04: Price validation bug ---")
_reset()
with app.app_context():
    r = client.post(
        "/products",
        data=json.dumps({"name": "Negative Widget", "price": -10}),
        content_type="application/json",
    )
    body = r.get_json()
    check(
        "POST /products price=-10 returns 201 (bug: no validation)",
        r.status_code == 201,
        "got {}, body={}".format(r.status_code, body),
    )
    check(
        "Stored product has price=-10 (bug: accepted as-is)",
        body is not None and body.get("price") == -10,
        "price={}".format(body.get("price") if body else "N/A"),
    )


# =============================================================================
# R05 BUG - GET /admin/users with NO token must return 200 (no auth check)
# =============================================================================
print("\n--- R05: Admin auth bug ---")
_reset()
with app.app_context():
    # No Authorization header at all
    r = client.get("/admin/users")
    check(
        "GET /admin/users (no token) returns 200 (bug: no auth check)",
        r.status_code == 200,
        "got {}".format(r.status_code),
    )

    # Also test with a regular-user token - should still be 200 (bug)
    users[1] = {
        "id": 1, "username": "alice", "email": "alice@example.com",
        "password_hash": b"$2b$12$placeholder", "role": "user",
    }
    auth_tokens["user_token_abc"] = {"user_id": 1, "role": "user"}

    r = client.get("/admin/users", headers={"Authorization": "Bearer user_token_abc"})
    check(
        "GET /admin/users (regular-user token) returns 200 (bug: no role check)",
        r.status_code == 200,
        "got {}".format(r.status_code),
    )


# =============================================================================
# R08 BUG - DELETE /products/1 leaves stale cart items
# =============================================================================
print("\n--- R08: Cascade delete bug ---")
_reset()
with app.app_context():
    # Seed a user + auth token
    users[1] = {
        "id": 1, "username": "bob", "email": "bob@example.com",
        "password_hash": b"$2b$12$placeholder", "role": "user",
    }
    auth_tokens["tok_bob"] = {"user_id": 1, "role": "user"}

    # Create a product via the API
    r = client.post(
        "/products",
        data=json.dumps({"name": "Doomed Product", "price": 9.99}),
        content_type="application/json",
    )
    assert r.status_code == 201, "create product failed: {}".format(r.status_code)
    product_id = r.get_json()["id"]

    # Add it to the cart
    r = client.post(
        "/cart/items",
        data=json.dumps({"product_id": product_id, "quantity": 2}),
        content_type="application/json",
        headers={"Authorization": "Bearer tok_bob"},
    )
    assert r.status_code == 201, "add to cart failed: {}".format(r.status_code)

    # Confirm item is in cart before deletion
    r = client.get("/cart", headers={"Authorization": "Bearer tok_bob"})
    cart_before = r.get_json()["items"]
    check(
        "Cart has 1 item before product deletion",
        len(cart_before) == 1,
        "items={}".format(cart_before),
    )

    # Delete the product
    r = client.delete("/products/{}".format(product_id))
    check(
        "DELETE /products/{} returns 200".format(product_id),
        r.status_code == 200,
        "got {}".format(r.status_code),
    )

    # Confirm product is gone
    r = client.get("/products/{}".format(product_id))
    check(
        "Product is deleted (GET returns 404)",
        r.status_code == 404,
        "got {}".format(r.status_code),
    )

    # BUG: cart item must STILL be present (no cascade delete)
    r = client.get("/cart", headers={"Authorization": "Bearer tok_bob"})
    cart_after = r.get_json()["items"]
    check(
        "Cart still has stale item after product deletion (bug: no cascade)",
        len(cart_after) == 1 and cart_after[0]["product_id"] == product_id,
        "items={}".format(cart_after),
    )


# =============================================================================
# Summary
# =============================================================================
passed = sum(results)
total  = len(results)
sep = "-" * 60
print("\n" + sep)
print("  Smoke test: {}/{} checks passed".format(passed, total))
if passed == total:
    print("  All seeded bugs confirmed [OK]")
else:
    print("  WARNING: some checks failed - review output above")
print(sep + "\n")

sys.exit(0 if passed == total else 1)
