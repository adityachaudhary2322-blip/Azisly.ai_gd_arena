"""Post-GD session evaluation engine for GD Arena.

Parses complete session transcripts and calculates:
- Speaking time percentage (User vs Panel)
- Interruptions handled
- Initiative score (1 - 10)
- Qualitative criterion-based feedback citing exact verbatim quotes.
Strictly adheres to SCHEMA.md contract.
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


def calculate_speaking_metrics(
    transcripts: List[Dict[str, Any]],
    interruptions_count: int,
) -> Dict[str, int]:
    """Calculate numerical metrics from the session transcript."""
    user_words = 0
    total_words = 0
    user_turns = 0
    total_turns = len(transcripts)
    user_spoke_early = False

    for idx, entry in enumerate(transcripts):
        speaker = entry.get("speaker", "")
        text = entry.get("text", "")
        words = len(re.findall(r"\w+", text))
        total_words += words

        if speaker.lower() in ("user", "candidate"):
            user_words += words
            user_turns += 1
            if idx <= 2:
                user_spoke_early = True

    # Speaking time % based on relative word volume
    if total_words > 0:
        speaking_time_user_percent = int(round((user_words / total_words) * 100))
    else:
        speaking_time_user_percent = 0

    # Initiative score out of 10 based on standard Indian GD assessment criteria:
    # - Early entry / Icebreaking
    # - Sustained contributions (turns)
    # - Assertiveness / Interruptions handled
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
        "speaking_time_user_percent": speaking_time_user_percent,
        "interruptions_handled": interruptions_count,
        "initiative_score": initiative_score,
    }


def generate_heuristic_feedback(
    transcripts: List[Dict[str, Any]],
    metrics: Dict[str, int],
) -> List[Dict[str, str]]:
    """Generate structured qualitative feedback with verbatim quote citations."""
    user_entries = [
        e for e in transcripts
        if e.get("speaker", "").lower() in ("user", "candidate") and e.get("text")
    ]

    feedback: List[Dict[str, str]] = []

    if user_entries:
        # 1. Idea Building & Synthesis
        first_user_text = user_entries[0]["text"]
        # Extract a crisp verbatim snippet (up to 60 characters or full sentence)
        snippet = first_user_text.strip()
        if len(snippet) > 80:
            snippet = snippet[:77].rsplit(" ", 1)[0] + "..."

        feedback.append({
            "criterion": "Idea Building",
            "quote": snippet,
            "analysis": (
                "Constructive initiative shown; grounded the topic with forward-looking perspective "
                "allowing peers to build on the framework."
            ),
        })

        # 2. Collaborative Phrasing / Group Dynamics
        if len(user_entries) > 1:
            second_text = user_entries[1]["text"].strip()
            if len(second_text) > 80:
                second_snippet = second_text[:77].rsplit(" ", 1)[0] + "..."
            else:
                second_snippet = second_text

            feedback.append({
                "criterion": "Collaboration & Bridging",
                "quote": second_snippet,
                "analysis": (
                    "Active participation maintained momentum in the discussion; "
                    "bridged conversational flow and handled panel dynamics effectively."
                ),
            })
        else:
            feedback.append({
                "criterion": "Sustained Participation",
                "quote": snippet,
                "analysis": (
                    "Strong opening contribution, but would benefit from intervening at least 2-3 times "
                    "across the mid and closing phases of the GD to anchor the final consensus."
                ),
            })
    else:
        # User didn't speak during the session
        feedback.append({
            "criterion": "Initiative & Voice Presence",
            "quote": "N/A (No speech recorded from user)",
            "analysis": (
                "Candidate remained passive during the discussion. In Indian placement GDs, "
                "entering within the first 60-90 seconds is critical for securing evaluators' attention."
            ),
        })

    # 3. Interruption Handling
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

    Returns:
        {
            "type": "final_report",
            "metrics": {
                "speaking_time_user_percent": int,
                "interruptions_handled": int,
                "initiative_score": int
            },
            "feedback": [
                {
                    "criterion": str,
                    "quote": str,
                    "analysis": str
                }
            ]
        }
    """
    metrics = calculate_speaking_metrics(transcripts, interruptions_count)
    feedback = generate_heuristic_feedback(transcripts, metrics)

    return {
        "type": "final_report",
        "metrics": metrics,
        "feedback": feedback,
    }
