"""
auth/users.py — User registration and password hashing.

R02: User passwords must be stored as bcrypt hashes, never in plaintext.
     bcrypt.hashpw is used; the stored value always starts with $2b$.
"""
import bcrypt
from flask import Blueprint, request, jsonify
from notifications import send_registration_email

users_bp = Blueprint("users", __name__)


def hash_password(plaintext: str) -> bytes:
    """Return a bcrypt hash of the plaintext password."""
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt())


def check_password(plaintext: str, hashed: bytes) -> bool:
    """Return True if plaintext matches the stored bcrypt hash."""
    return bcrypt.checkpw(plaintext.encode("utf-8"), hashed)


# ── HTTP endpoints ─────────────────────────────────────────────────────────────

@users_bp.route("/register", methods=["POST"])
def register():
    """
    POST /auth/register

    Body: {username, email, password}
    Stores password as bcrypt hash — never in plaintext (R02).
    Sends a registration confirmation email (R09 — may be unproven in sandbox).
    """
    from app import users, next_id
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    email    = data.get("email", "").strip()
    password = data.get("password", "")

    if not username or not email or not password:
        return jsonify(error="username, email, and password are required"), 400

    # Check for duplicate username
    for u in users.values():
        if u["username"] == username:
            return jsonify(error="username already taken"), 409

    # R02: store bcrypt hash, never raw string
    password_hash = hash_password(password)

    user_id = next_id("user")
    user = {
        "id":            user_id,
        "username":      username,
        "email":         email,
        "password_hash": password_hash,   # bytes — starts with b'$2b$'
        "role":          "user",
    }
    users[user_id] = user

    # R09: attempt to send confirmation email (may fail in sandbox — UNPROVEN)
    send_registration_email(email)

    return jsonify(id=user_id, username=username, email=email, role="user"), 201


@users_bp.route("/<int:user_id>", methods=["GET"])
def get_user(user_id: int):
    """GET /auth/<user_id>  — return public user info (no password hash)."""
    from app import users
    user = users.get(user_id)
    if not user:
        return jsonify(error="user not found"), 404
    return jsonify(id=user["id"], username=user["username"],
                   email=user["email"], role=user["role"]), 200
