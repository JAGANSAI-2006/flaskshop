"""
auth/tokens.py — Password reset token logic.

R01: Password reset tokens must expire after 15 minutes.
     expires_in is set to 900 (15 * 60 seconds).
"""
import time
import secrets
from flask import Blueprint, request, jsonify

tokens_bp = Blueprint("tokens", __name__)


def generate_reset_token(user_id: int) -> dict:
    """Create a password reset token that expires in 15 minutes (900 seconds)."""
    token = secrets.token_urlsafe(32)
    token_data = {
        "token": token,
        "user_id": user_id,
        "expires_in": 900,          # R01: exactly 15 * 60 seconds
        "created_at": time.time(),
    }
    # Store in shared reset_tokens dict
    from app import reset_tokens
    reset_tokens[token] = token_data
    return token_data


def is_token_valid(token_str: str) -> bool:
    """Return True if the token exists and has not yet expired."""
    from app import reset_tokens
    entry = reset_tokens.get(token_str)
    if not entry:
        return False
    age = time.time() - entry["created_at"]
    return age < entry["expires_in"]


# ── HTTP endpoints ─────────────────────────────────────────────────────────────

@tokens_bp.route("/reset-token", methods=["POST"])
def request_reset_token():
    """POST /auth/reset-token  — issue a password-reset token for a user."""
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify(error="user_id required"), 400
    from app import users
    if user_id not in users:
        return jsonify(error="user not found"), 404
    token_data = generate_reset_token(user_id)
    return jsonify(token_data), 201


@tokens_bp.route("/reset-token/verify", methods=["POST"])
def verify_reset_token():
    """POST /auth/reset-token/verify  — check whether a token is still valid."""
    data = request.get_json(silent=True) or {}
    token_str = data.get("token", "")
    valid = is_token_valid(token_str)
    return jsonify(valid=valid), 200
