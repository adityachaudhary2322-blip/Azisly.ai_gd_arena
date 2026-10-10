"""Sarvam AI Chat Completions client wrapper.

Provides asynchronous access to Sarvam's LLM endpoint (sarvam-2b / sarvam-m)
for persona dialogue generation and post-session GD evaluations.
Supports deterministic mock bypass and multi-language Indic support (en-IN, hi-IN, etc.).
"""

import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Deterministic dialogue lines per persona for English mock mode
MOCK_PERSONA_DIALOGUE_EN: Dict[str, str] = {
    "moderator": (
        "Let us structure our thoughts into economic impact and ethical considerations "
        "so we maintain a balanced perspective."
    ),
    "dominator": (
        "I have to challenge that premise directly; in fast-paced markets, "
        "execution speed always trumps theoretical caution."
    ),
    "data_driven": (
        "Looking at recent industry benchmarks, empirical data from NASSCOM "
        "indicates a net 14% expansion in high-skill roles."
    ),
    "bridger": (
        "I see a very constructive middle ground between Kabir's push for speed "
        "and Anushka's data on talent transition."
    ),
    "quiet_analyst": (
        "Beyond immediate operational efficiency, the real strategic differentiator "
        "lies in long-term institutional resilience."
    ),
}

# Deterministic dialogue lines per persona for Hindi / Hinglish mock mode
MOCK_PERSONA_DIALOGUE_HI: Dict[str, str] = {
    "moderator": (
        "Aaiye hum is discussion ko structured tareeqe se aage badhayein aur dono pehluon ko samjhein."
    ),
    "dominator": (
        "Main is point se poori tarah disagree karta hoon; ground reality par execution speed sabse zaroori hai."
    ),
    "data_driven": (
        "Agar hum NASSCOM ke empirical data ko dekhein, toh net 14% growth high-skill jobs mein dikh rahi hai."
    ),
    "bridger": (
        "Main Kabir aur candidate dono ke viewpoints ke beech ek constructive middle ground dekh sakti hoon."
    ),
    "quiet_analyst": (
        "Short-term productivity ke alawa, long-term institutional resilience par focus karna sabse critical hai."
    ),
}

MOCK_DEFAULT_REPLY = (
    "That raises a critical perspective that the panel should examine from multiple angles."
)

MOCK_EVALUATION_REPORT: Dict[str, Any] = {
    "type": "final_report",
    "metrics": {
      "speaking_time_user_percent": 24,
      "interruptions_handled": 3,
      "initiative_score": 8,
      "speaking_time_distribution": {
        "User": 24,
        "Arjun": 20,
        "Kabir": 24,
        "Anushka": 18,
        "Priya": 14,
      },
    },
    "feedback": [
      {
        "criterion": "Idea Building",
        "quote": "Adding to Priya's point regarding regulation...",
        "analysis": "Strong collaborative phrasing; bridged between two divergent viewpoints.",
      },
      {
        "criterion": "Argumentation & Scoping",
        "quote": "I believe artificial intelligence will significantly transform the job market...",
        "analysis": "Clear initial framing with balanced thematic breakdown.",
      },
    ],
}


def _detect_mock_response(messages: List[Dict[str, str]]) -> str:
    """Select appropriate deterministic mock text based on message contents and target language."""
    full_text = " ".join(m.get("content", "") for m in messages).lower()

    # Check if request is for evaluation or JSON schema report
    if "final_report" in full_text or "evaluat" in full_text or "json" in full_text:
        return json.dumps(MOCK_EVALUATION_REPORT)

    # Determine dialogue bank based on language indicator
    is_hindi = "hi-in" in full_text or "hindi" in full_text or "hinglish" in full_text
    dialogues = MOCK_PERSONA_DIALOGUE_HI if is_hindi else MOCK_PERSONA_DIALOGUE_EN

    # Check for specific persona system prompts or names
    if "arjun" in full_text or "moderator" in full_text:
        return dialogues["moderator"]
    if "kabir" in full_text or "dominator" in full_text:
        return dialogues["dominator"]
    if "anushka" in full_text or "data_driven" in full_text or "data-driven" in full_text:
        return dialogues["data_driven"]
    if "priya" in full_text or "bridger" in full_text:
        return dialogues["bridger"]
    if "rohan" in full_text or "quiet_analyst" in full_text or "quiet analyst" in full_text:
        return dialogues["quiet_analyst"]

    return MOCK_DEFAULT_REPLY


async def get_sarvam_completion(
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 150,
    model: str = "sarvam-2b",
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Call Sarvam AI chat completions API or return deterministic mock response.

    Args:
        messages: List of chat messages with 'role' and 'content'.
        temperature: Sampling temperature (default: 0.2).
        max_tokens: Maximum completion tokens (default: 150).
        model: Sarvam model name ('sarvam-2b' or 'sarvam-m').
        client: Optional httpx.AsyncClient for connection pooling / testing.

    Returns:
        String content of the model's completion.
    """
    if settings.MOCK_VOICE or not settings.SARVAM_API_KEY.strip():
        logger.debug("MOCK_VOICE active or missing API key. Returning deterministic Sarvam mock completion.")
        return _detect_mock_response(messages)

    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "model": model or settings.SARVAM_LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async def _post(c: httpx.AsyncClient) -> str:
        resp = await c.post(
            settings.SARVAM_LLM_URL,
            headers=headers,
            json=payload,
            timeout=15.0,
        )
        if resp.status_code == 400 and "sarvam-105b" in resp.text:
            payload["model"] = "sarvam-105b"
            resp = await c.post(
                settings.SARVAM_LLM_URL,
                headers=headers,
                json=payload,
                timeout=15.0,
            )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"Empty choices in Sarvam completion response: {data}")
        content = choices[0].get("message", {}).get("content", "")
        return content.strip()

    try:
        if client is not None:
            return await _post(client)
        async with httpx.AsyncClient() as new_client:
            return await _post(new_client)
    except Exception as exc:
        logger.warning("Sarvam LLM call failed (%s). Falling back to deterministic mock response.", exc)
        return _detect_mock_response(messages)
