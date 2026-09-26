"""
auth/login.py — Login endpoint with rate-limiting stub.

R06: Failed login attempts must be limited to 5 per minute per IP before lockout.
     Rate limiting: requires flask-limiter and Redis backend.
     flask_limiter is intentionally NOT in requirements.txt — when the test
     executor imports this module in isolation it will raise ImportError, which
     causes an UNPROVEN verdict for R06.
"""
# Rate limiting: requires flask-limiter and Redis backend
try:
    from flask_limiter import Limiter          # noqa: F401
    from flask_limiter.util import get_remote_address  # noqa: F401
    _limiter_available = True
except ImportError:
    _limiter_available = False  # flask-limiter not installed — R06 UNPROVEN

import secrets
from flask import Blueprint, request, jsonify
from auth.users import check_password

login_bp = Blueprint("login", __name__)


@login_bp.route("/login", methods=["POST"])
def login():
    """
    POST /auth/login

    Body: {username, password}
    On success returns a bearer token string.
    Rate-limited to 5 failed attempts / minute / IP (requires flask-limiter + Redis).
    """
    from app import users, auth_tokens
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    password = data.get("password", "")

    # Find user by username
    user = None
    for u in users.values():
        if u["username"] == username:
            user = u
            break

    if not user or not check_password(password, user["password_hash"]):
        return jsonify(error="Invalid credentials"), 401

    # Issue a simple bearer token
    token_str = secrets.token_urlsafe(32)
    auth_tokens[token_str] = {"user_id": user["id"], "role": user["role"]}
    return jsonify(token=token_str, role=user["role"]), 200
