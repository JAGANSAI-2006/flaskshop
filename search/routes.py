"""
search/routes.py — Product search.

R11: Search results must be returned in descending order of relevance score.
     UNPROVEN: The relevance score is computed with random.random() which is
     non-deterministic. There is no stable assertion to make against the ordering.
"""
import random
from flask import Blueprint, request, jsonify

search_bp = Blueprint("search", __name__)


@search_bp.route("", methods=["GET"])
def search_products():
    """
    GET /search?q=<query>

    Returns products whose name contains the query string.
    Each result is annotated with a non-deterministic relevance score
    (R11 UNPROVEN — score is random, ordering is not assertable).
    """
    from app import products

    query = request.args.get("q", "").lower().strip()
    if not query:
        return jsonify(results=[]), 200

    results = []
    for product in products.values():
        if query in product["name"].lower():
            # R11: non-deterministic relevance score — not sortable in tests
            score = random.random()  # noqa: S311
            results.append({
                "id":              product["id"],
                "name":            product["name"],
                "price":           product["price"],
                "relevance_score": score,
            })

    # Sort descending by score (but the score itself is random each request)
    results.sort(key=lambda r: r["relevance_score"], reverse=True)

    return jsonify(results=results), 200
