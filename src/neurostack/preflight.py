"""Pre-flight checks for Ollama connectivity and model availability."""

import logging

import httpx

log = logging.getLogger("neurostack")


class OllamaCheckResult:
    """Result of an Ollama pre-flight check."""

    def __init__(self):
        self.embed_ok: bool = False
        self.llm_ok: bool = False
        self.embed_error: str = ""
        self.llm_error: str = ""

    @property
    def any_ok(self) -> bool:
        return self.embed_ok or self.llm_ok


def check_ollama(
    embed_url: str,
    embed_model: str,
    llm_url: str,
    llm_model: str,
    timeout: float = 5.0,
) -> OllamaCheckResult:
    """Check Ollama connectivity and model availability.

    Returns an OllamaCheckResult with status for embedding and LLM services.
    Does not raise — all errors are captured in the result object.
    """
    result = OllamaCheckResult()

    # Check embedding service
    result.embed_ok, result.embed_error = _check_model(
        embed_url, embed_model, timeout
    )

    # Check LLM service (may be same or different URL)
    result.llm_ok, result.llm_error = _check_model(
        llm_url, llm_model, timeout
    )

    return result


def _check_model(
    base_url: str, model: str, timeout: float
) -> tuple[bool, str]:
    """Check if a specific model is available on an Ollama instance.

    Returns (ok, error_message).
    """
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=timeout)
        resp.raise_for_status()
    except httpx.ConnectError:
        return False, f"Cannot connect to Ollama at {base_url}"
    except httpx.TimeoutException:
        return False, f"Timeout connecting to Ollama at {base_url}"
    except httpx.HTTPStatusError as e:
        return False, f"Ollama returned {e.response.status_code} at {base_url}"
    except Exception as e:
        return False, f"Ollama check failed: {e}"

    try:
        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        # Match with or without :latest tag
        model_names = set()
        for m in models:
            model_names.add(m)
            if ":" in m:
                model_names.add(m.split(":")[0])
        model_base = model.split(":")[0] if ":" in model else model
        if model not in model_names and model_base not in model_names:
            available = ", ".join(sorted(models)) or "(none)"
            return (
                False,
                f"Model '{model}' not found. "
                f"Available: {available}. "
                f"Run: ollama pull {model}",
            )
    except Exception as e:
        return False, f"Failed to parse Ollama model list: {e}"

    return True, ""


def preflight_report(result: OllamaCheckResult) -> str:
    """Format a pre-flight check result as a user-friendly string."""
    lines = []
    if not result.embed_ok:
        lines.append(f"  Embeddings: UNAVAILABLE — {result.embed_error}")
        lines.append(
            "    Chunks will be indexed without embeddings "
            "(FTS5-only search)."
        )
    if not result.llm_ok:
        lines.append(f"  Summaries/Triples: UNAVAILABLE — {result.llm_error}")
        lines.append(
            "    Notes will be indexed without summaries or triples."
        )
    if lines:
        return (
            "Ollama pre-flight check:\n"
            + "\n".join(lines)
            + "\n  To fix: ensure Ollama is running and models are pulled."
        )
    return ""
