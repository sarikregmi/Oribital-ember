"""Optional local Qwen explanation adapter; it never performs calculations."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


def explain_result(result: dict[str, Any], endpoint: str = "http://localhost:11434/api/generate", model: str = "qwen3:0.6b", timeout: float = 8.0) -> dict[str, Any]:
    prompt = (
        "Explain this screening result plainly. Do not add physics, values, certainty, or safety claims. "
        "Preserve labels such as unknown, estimated, user-described, and screening-only. "
        "Say when evidence or data is missing.\n\n" + json.dumps(result, indent=2)
    )
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    request = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return {"status": "available", "model": model, "text": body.get("response", ""), "calculation_source": "Python"}
    except (OSError, URLError, TimeoutError) as error:
        return {"status": "unavailable", "model": model, "text": "Qwen explanation unavailable; inspect the structured Python result.", "error": str(error), "calculation_source": "Python"}
