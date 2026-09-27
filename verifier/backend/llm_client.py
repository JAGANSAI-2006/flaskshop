"""
llm_client.py — Thin wrapper around the IBM watsonx.ai SDK.

Provides a single `generate(prompt) -> str` function used by the
Intent Contract Generator and Test Generator pipeline steps.

Model: ibm/granite-3-3-8b-instruct (Granite 3.3 8B Instruct)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ibm_watsonx_ai import Credentials
from ibm_watsonx_ai.foundation_models import ModelInference
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams

from config import (
    GRANITE_MODEL_ID,
    GENERATION_DECODING_METHOD,
    GENERATION_MAX_NEW_TOKENS,
    GENERATION_TEMPERATURE,
    WATSONX_API_KEY,
    WATSONX_PROJECT_ID,
    WATSONX_URL,
    assert_credentials,
)

logger = logging.getLogger(__name__)


class WatsonxClient:
    """
    Minimal watsonx.ai client.

    Usage:
        client = WatsonxClient()
        text = client.generate("Reply with the word OK")
    """

    def __init__(self) -> None:
        assert_credentials()
        self._credentials = Credentials(
            url=WATSONX_URL,
            api_key=WATSONX_API_KEY,
        )
        self._params: Dict[str, Any] = {
            GenParams.DECODING_METHOD: GENERATION_DECODING_METHOD,
            GenParams.MAX_NEW_TOKENS: GENERATION_MAX_NEW_TOKENS,
            GenParams.TEMPERATURE: GENERATION_TEMPERATURE,
        }
        self._model = ModelInference(
            model_id=GRANITE_MODEL_ID,
            credentials=self._credentials,
            project_id=WATSONX_PROJECT_ID,
            params=self._params,
        )
        logger.info("WatsonxClient initialised (model=%s)", GRANITE_MODEL_ID)

    def generate(self, prompt: str) -> str:
        """
        Send a prompt to Granite and return the generated text.

        Raises RuntimeError on API failure.
        """
        try:
            response = self._model.generate_text(prompt=prompt)
            # generate_text returns a str directly in ibm-watsonx-ai >= 1.0
            if isinstance(response, str):
                return response.strip()
            # Older SDK versions return a dict
            if isinstance(response, dict):
                return response.get("results", [{}])[0].get("generated_text", "").strip()
            return str(response).strip()
        except Exception as exc:
            logger.error("WatsonxClient.generate failed: %s", exc)
            raise RuntimeError(f"LLM call failed: {exc}") from exc

    def generate_json(self, prompt: str) -> Dict[str, Any]:
        """
        Call the model and parse the response as JSON.

        Returns an empty dict and logs a warning if the output is not valid JSON.
        """
        raw = self.generate(prompt)
        # Strip markdown code fences if the model wraps output in ```json … ```
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                line for line in lines
                if not line.startswith("```")
            )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("generate_json: could not parse JSON — %s\nRaw output:\n%s", exc, raw)
            return {}


# Module-level singleton — created lazily to avoid crashing at import time
# when credentials are not yet set.
_client: WatsonxClient | None = None


def get_client() -> WatsonxClient:
    """Return the shared WatsonxClient instance, creating it on first call."""
    global _client
    if _client is None:
        _client = WatsonxClient()
    return _client
