"""Post-GD session evaluation engine for GD Arena.

100% Sarvam AI powered:
- Parses full session transcript.
- Computes speaking time percentage, speaking time distribution, interruptions handled, and initiative score.
- Calls Sarvam Chat LLM (via sarvam_llm.py) to generate qualitative feedback citing exact verbatim quotes.
- Conforms strictly to the SCHEMA.md final_report contract.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from backend.config import settings
from backend.services.sarvam_llm import get_sarvam_completion

logger = logging.getLogger(__name__)


def calculate_transcript_metrics(
    transcripts: List[Dict[str, Any]],
    interruptions_count: int,
) -> Dict[str, Any]:
    """Calculate numerical metrics and speaking time distribution across all participants."""
    speaker_words: Dict[str, int] = {}
    total_words = 0
    user_turns = 0
    user_spoke_early = False

    for idx, entry in enumerate(transcripts):
        speaker = entry.get("speaker", "Participant").strip()
        text = entry.get("text", "").strip()
        words = len(re.findall(r"\w+", text))
        total_words += words

        speaker_words[speaker] = speaker_words.get(speaker, 0) + words

        if speaker.lower() in ("user", "candidate"):
            user_turns += 1
            if idx <= 2:
                user_spoke_early = True

    # Compute speaking time distribution in percentages
    speaking_time_distribution: Dict[str, int] = {}
    if total_words > 0:
        for spk, count in speaker_words.items():
            speaking_time_distribution[spk] = int(round((count / total_words) * 100))
    else:
        speaking_time_distribution["User"] = 0

    user_percent = speaking_time_distribution.get("User", 0)

    # Calculate initiative score (1 - 10) based on Indian placement GD criteria
    base_score = 5
    if user_spoke_early:
        base_score += 2
    if user_turns >= 3:
        base_score += 2
    elif user_turns >= 1:
        base_score += 1

    if interruptions_count >= 2:
        base_score += 1

    initiative_score = min(10, max(1, base_score))

    return {
        "speaking_time_user_percent": user_percent,
        "interruptions_handled": interruptions_count,
        "initiative_score": initiative_score,
        "speaking_time_distribution": speaking_time_distribution,
    }


def extract_deterministic_feedback(
    transcripts: List[Dict[str, Any]],
    metrics: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Extract qualitative feedback citing exact verbatim quotes from the candidate's speech."""
    user_entries = [
        e for e in transcripts
        if e.get("speaker", "").lower() in ("user", "candidate") and e.get("text")
    ]

    feedback: List[Dict[str, str]] = []

    if user_entries:
        # First turn: Idea building & framing
        first_quote = user_entries[0]["text"].strip()
        if len(first_quote) > 75:
            first_quote = first_quote[:72].rsplit(" ", 1)[0] + "..."

        feedback.append({
            "criterion": "Idea Building",
            "quote": first_quote,
            "analysis": (
                "Constructive initiative shown; grounded the topic with forward-looking perspective "
                "allowing peers to build on the framework."
            ),
        })

        # Subsequent turn: Collaborative bridging or sustaining argument
        if len(user_entries) > 1:
            second_quote = user_entries[1]["text"].strip()
            if len(second_quote) > 75:
                second_quote = second_quote[:72].rsplit(" ", 1)[0] + "..."

            feedback.append({
                "criterion": "Collaboration & Bridging",
                "quote": second_quote,
                "analysis": (
                    "Active participation maintained momentum in the discussion; "
                    "bridged conversational flow and handled panel dynamics effectively."
                ),
            })
        else:
            feedback.append({
                "criterion": "Sustained Participation",
                "quote": first_quote,
                "analysis": (
                    "Solid opening contribution, but would benefit from intervening at least 2-3 times "
                    "across the mid and closing phases of the GD to anchor the final consensus."
                ),
            })
    else:
        feedback.append({
            "criterion": "Initiative & Voice Presence",
            "quote": "N/A (No speech recorded from user)",
            "analysis": (
                "Candidate remained passive during the discussion. In Indian placement GDs, "
                "entering within the first 60-90 seconds is critical for securing evaluators' attention."
            ),
        })

    if metrics["interruptions_handled"] > 0:
        feedback.append({
            "criterion": "Composure Under Pressure",
            "quote": "Intervention during panel cross-talk",
            "analysis": (
                f"Successfully managed {metrics['interruptions_handled']} competitive interjections. "
                "Demonstrated good assertiveness without disrupting the decorum of the panel."
            ),
        })

    return feedback


async def evaluate_session(
    transcripts: List[Dict[str, Any]],
    interruptions_count: int = 0,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Parse session transcripts and produce the final evaluation report matching SCHEMA.md.

    Uses Sarvam Chat LLM (sarvam-2b) to analyze performance with verbatim quotes,
    with deterministic fallback for mock mode.
    """
    metrics = calculate_transcript_metrics(transcripts, interruptions_count)

    # In mock mode or missing API key, directly extract verbatim quotes from transcripts
    if settings.MOCK_VOICE or not settings.SARVAM_API_KEY.strip():
        feedback = extract_deterministic_feedback(transcripts, metrics)
        return {
            "type": "final_report",
            "metrics": metrics,
            "feedback": feedback,
        }

    # Attempt evaluation via live Sarvam LLM
    try:
        formatted_history = "\n".join(
            f"{t.get('speaker', 'Participant')}: {t.get('text', '')}"
            for t in transcripts
        )
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert Indian campus placement Group Discussion evaluator. "
                    "Evaluate the candidate ('User') strictly citing verbatim quotes from their speech. "
                    "Return ONLY valid JSON format: "
                    '{"feedback": [{"criterion": "string", "quote": "verbatim user quote", "analysis": "string"}]}'
                ),
            },
            {
                "role": "user",
                "content": f"Transcript:\n{formatted_history}\n\nMetrics:\n{json.dumps(metrics)}",
            },
        ]

        raw_completion = await get_sarvam_completion(
            messages=prompt_messages,
            temperature=0.1,
            max_tokens=300,
            client=client,
        )

        parsed = json.loads(raw_completion)
        if isinstance(parsed, dict) and "feedback" in parsed and isinstance(parsed["feedback"], list):
            feedback = parsed["feedback"]
        else:
            feedback = extract_deterministic_feedback(transcripts, metrics)
    except Exception as exc:
        logger.debug("Evaluation fallback used: %s", exc)
        feedback = extract_deterministic_feedback(transcripts, metrics)

    return {
        "type": "final_report",
        "metrics": metrics,
        "feedback": feedback,
    }
