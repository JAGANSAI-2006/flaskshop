# Requirement-to-Code Verifier

A developer tool that checks whether software requirements are actually
implemented in a codebase.

The verifier turns plain-language requirements into structured intent,
traces each requirement to relevant source code, generates or executes
verification tests, and produces an evidence-backed verdict:

- **PROVEN** — implementation evidence and verification test support the requirement.
- **FAILED** — verification test demonstrates that the requirement is violated.
- **UNPROVEN** — available evidence is insufficient to verify the requirement.

## How It Works

```text
Requirement
     ↓
Intent Contract
     ↓
Repository Ingestion
     ↓
Code Tracing
     ↓
Verification Test
     ↓
Evidence Collection
     ↓
PROVEN / FAILED / UNPROVEN
# FlaskShop — Demo Repository for Requirement-to-Code Verifier

A minimal Python/Flask e-commerce API purpose-built to demonstrate the
**Requirement-to-Code Verifier**. It contains 12 traceable requirements, 3
intentionally seeded bugs, and 3 requirements that are deliberately unverifiable
in a sandboxed environment.

---

## Quick Start

```bash
pip install flask bcrypt
python app.py          # starts on http://localhost:5000
```

---

## Project Structure

```
demo/flaskshop/
├── app.py                  # Flask application factory + in-memory stores
├── notifications.py        # Email stub (R09)
├── requirements.txt        # flask, bcrypt only — flask-limiter intentionally absent
├── smoke_test.py           # Confirms all 3 seeded bugs behave as expected
├── auth/
│   ├── tokens.py           # Password reset token logic (R01)
│   ├── users.py            # User registration + bcrypt hashing (R02)
│   └── login.py            # Login + rate-limiting stub (R06)
├── products/
│   └── routes.py           # Product CRUD — price validation BUG (R04), cascade BUG (R08)
├── cart/
│   └── routes.py           # Cart management (R03, R07)
├── orders/
│   └── routes.py           # Order history, pagination (R10)
├── admin/
│   └── routes.py           # Admin endpoints — missing auth BUG (R05)
└── search/
    └── routes.py           # Product search stub (R11)
```

---

## In-Memory Storage

All data lives in plain Python dicts — no database, no migrations.

| Store | Key | Value |
|-------|-----|-------|
| `users` | user_id (int) | `{id, username, email, password_hash, role}` |
| `reset_tokens` | token_str | `{token, user_id, expires_in, created_at}` |
| `products` | product_id (int) | `{id, name, price}` |
| `carts` | user_id (int) | `[{product_id, quantity}]` |
| `orders` | user_id (int) | `[{id, items, total, created_at}]` |
| `auth_tokens` | token_str | `{user_id, role}` |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Register user (bcrypt hash stored) |
| POST | `/auth/login` | Login → bearer token |
| POST | `/auth/reset-token` | Request password reset token |
| POST | `/auth/reset-token/verify` | Check token validity |
| GET | `/products` | List all products |
| GET | `/products/<id>` | Get product |
| POST | `/products` | Create product (**BUG: no price validation**) |
| PUT | `/products/<id>` | Update product |
| DELETE | `/products/<id>` | Delete product (**BUG: no cascade delete**) |
| GET | `/cart` | Get cart items |
| POST | `/cart/items` | Add item to cart |
| DELETE | `/cart/items/<product_id>` | Remove item from cart |
| GET | `/cart/total` | Get cart total (with optional discount code) |
| POST | `/cart/checkout` | Place order (400 if cart empty) |
| GET | `/orders` | Paginated order history (max 20/page) |
| GET | `/orders/<id>` | Get single order |
| GET | `/admin/users` | List all users (**BUG: no auth check**) |
| GET | `/admin/products` | List all products (**BUG: no auth check**) |
| GET | `/admin/orders` | List all orders (**BUG: no auth check**) |
| GET | `/search?q=<query>` | Search products |

---

## The 12 Requirements and Expected Verdicts

| ID | Requirement | Expected Verdict | Reason |
|----|-------------|-----------------|--------|
| R01 | Password reset tokens must expire after 15 minutes. | **PROVEN** | `expires_in = 900` (15×60) is set in `auth/tokens.py` |
| R02 | User passwords must be stored as bcrypt hashes, never in plaintext. | **PROVEN** | `bcrypt.hashpw` used; stored value starts with `$2b$` |
| R03 | A user must not be able to place an order with an empty cart. | **PROVEN** | `POST /cart/checkout` returns HTTP 400 for empty cart |
| R04 | Product prices must never be negative. | **FAILED** ❌ | **BUG**: `POST /products` accepts `price=-10` with HTTP 201 — no validation |
| R05 | Admin endpoints must require an admin role; regular users must receive HTTP 403. | **FAILED** ❌ | **BUG**: No auth middleware in `admin/routes.py` — any caller gets 200 |
| R06 | Failed login attempts must be limited to 5 per minute per IP before lockout. | **UNPROVEN** ⚠️ | `flask_limiter` is imported in `auth/login.py` but not in `requirements.txt` → ImportError |
| R07 | The cart total must correctly apply percentage discount codes. | **PROVEN** | `GET /cart/total?discount_code=SAVE10` correctly reduces total by 10% |
| R08 | Deleting a product must also delete all associated cart items. | **FAILED** ❌ | **BUG**: `DELETE /products/<id>` removes the product but cart items remain |
| R09 | Users must receive an email confirmation after successful registration. | **UNPROVEN** ⚠️ | `send_registration_email()` exists but SMTP not configured in sandbox |
| R10 | Order history must be paginated with a maximum of 20 orders per page. | **PROVEN** | `GET /orders?page=1` returns at most 20 orders; enforced by `PAGE_SIZE = 20` |
| R11 | Search results must be returned in descending order of relevance score. | **UNPROVEN** ⚠️ | Search exists but `relevance_score` is `random.random()` — non-deterministic |
| R12 | All API endpoints must return JSON, never HTML error pages. | **PROVEN** | `@app.errorhandler` registered for 400/401/403/404/405/500 — all return JSON |

### Summary

| Verdict | Count | Requirements |
|---------|-------|-------------|
| PROVEN | 6 | R01, R02, R03, R07, R10, R12 |
| FAILED | 3 | R04, R05, R08 |
| UNPROVEN | 3 | R06, R09, R11 |

---

## Seeded Bugs — Details

### R04 Bug — Missing Price Validation (`products/routes.py`)

**Location**: `POST /products` handler  
**Bug**: No `if price < 0` check. A product with `price=-10` is accepted and stored with HTTP 201.  
**Correct behaviour**: Should return HTTP 400 with `{"error": "price must not be negative"}`.

### R05 Bug — Missing Admin Auth Middleware (`admin/routes.py`)

**Location**: All three routes in `admin/routes.py`  
**Bug**: No bearer-token check, no role check. Any request receives HTTP 200 regardless of who sent it.  
**Correct behaviour**: Should check `Authorization` header, decode token, and return 403 if role ≠ `"admin"`.

### R08 Bug — No Cascade Delete (`products/routes.py`)

**Location**: `DELETE /products/<id>` handler  
**Bug**: Deletes the product from `products` dict but does not clean up `carts`. Cart items referencing the deleted product remain.  
**Correct behaviour**: Should iterate all user carts and remove items where `product_id` matches the deleted product.

---

## Discount Codes (R07)

| Code | Discount |
|------|----------|
| `SAVE10` | 10% off |
| `SAVE20` | 20% off |
| `HALFOFF` | 50% off |

Usage: `GET /cart/total?discount_code=SAVE10`
