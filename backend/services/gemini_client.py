"""Gemini API client for contextual speech generation in GD Arena."""

import logging
import random
from typing import List, Dict, Any, Optional
import httpx

from backend.config import settings
from backend.engine.personas import Persona

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# Fallback contextual replies per persona for realistic campus GD simulations
FALLBACK_RESPONSES: Dict[str, List[str]] = {
    "moderator": [
        "Let us structure our thoughts into economic impact and ethical considerations so we have a balanced view.",
        "That is an insightful observation from the candidate. Let us also invite other perspectives on the operational challenges.",
        "We have heard compelling points on innovation; let us now consider how this affects grassroots employment.",
        "To summarize our current direction, we see clear productivity gains, but what about the regulatory framework?",
    ],
    "dominator": [
        "I have to challenge that premise directly. In real-world enterprise deployment, efficiency always trumps theoretical caution.",
        "Wait, let's look at the harsh truth here. Companies aren't going to slow down innovation just because of market friction.",
        "I strongly disagree with that conservative view. If we don't aggressively automate, global competitors will outpace us.",
        "Let's not be idealistic. The market rewards first-movers, not those who wait for perfect safety guidelines.",
    ],
    "data_driven": [
        "Looking at recent industry benchmarks, over 62% of Tier-1 tech firms reported a 3x ROI within six months of adoption.",
        "Empirical studies from NASSCOM suggest that net job creation will actually outpace displacements by 14% by 2030.",
        "The quantitative trade-off is stark: capital expenditure drops by 35%, while productivity per developer increases by 40%.",
        "Statistically, if we look at the last three economic cycles, technology transitions consistently elevate median wage growth.",
    ],
    "bridger": [
        "I see a very constructive middle ground between Priya's point on speed and the candidate's concern regarding workforce reskilling.",
        "Building directly on what the candidate just highlighted, we can pair rapid deployment with structured transition programs.",
        "That really ties our two threads together nicely. What if we phase adoption gradually while retaining the core competitive edge?",
        "To connect Anushka's statistics with Priya's market reality, the solution lies in continuous organizational upskilling.",
    ],
}


async def generate_persona_utterance(
    persona: Persona,
    topic: str,
    recent_transcripts: List[Dict[str, Any]],
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Generate in-character dialogue for a GD persona using Gemini or fallback."""
    # Check if a live Gemini API key is configured
    api_key = settings.GEMINI_API_KEY
    is_live_key = (
        api_key
        and api_key != "your_gemini_key_here"
        and not settings.MOCK_VOICE
    )

    if not is_live_key:
        responses = FALLBACK_RESPONSES.get(persona.avatar_id, FALLBACK_RESPONSES["moderator"])
        return random.choice(responses)

    # Format conversation history
    history_text = "\n".join(
        f"{entry.get('speaker', 'Participant')}: {entry.get('text', '')}"
        for entry in recent_transcripts[-5:]
    )
    prompt = persona.get_prompt_context(topic=topic, recent_transcript=history_text)

    url = f"{GEMINI_API_BASE}?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 60,
            "temperature": 0.8,
        },
    }

    async def _post(c: httpx.AsyncClient) -> str:
        resp = await c.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                text = parts[0].get("text", "").strip()
                # Clean any accidental speaker name prefixes
                if ":" in text and len(text.split(":")[0]) < 15:
                    text = text.split(":", 1)[1].strip()
                return text
        raise ValueError("Empty response from Gemini API")

    try:
        if client is not None:
            return await _post(client)
        async with httpx.AsyncClient() as c:
            return await _post(c)
    except Exception as exc:
        logger.warning("Gemini generation failed (%s). Falling back to persona script.", exc)
        responses = FALLBACK_RESPONSES.get(persona.avatar_id, FALLBACK_RESPONSES["moderator"])
        return random.choice(responses)
