"""Persona definitions for GD Arena Indian Campus Placement Group Discussion dynamics.

Provides 4 distinct personalities:
1. Moderator ('Arjun'): Structural facilitator, tracks time, tempers conflicts, scopes topics.
2. Dominator ('Priya'): Aggressive challenger, high initiative, challenges assumptions, claims airtime.
3. Data-Driven ('Anushka'): Analytical skeptic, cites reports, metrics, ROI, and empirical data.
4. Bridger ('Meera'): Collaborative synthesizer, acknowledges peers, bridges divergent viewpoints.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Persona:
    """Represents a GD AI Participant personality profile."""

    avatar_id: str
    name: str
    voice_speaker: str
    role_title: str
    turn_weight: float
    system_prompt: str

    def get_prompt_context(self, topic: str, recent_transcript: str) -> str:
        """Format the conversational generation prompt for the LLM."""
        return (
            f"{self.system_prompt}\n\n"
            f"GD Topic: \"{topic}\"\n"
            f"Recent Transcript Flow:\n{recent_transcript}\n\n"
            f"Instructions:\n"
            f"- Respond naturally as {self.name} in 1 to 2 spoken sentences (maximum 40 words).\n"
            f"- React directly to the last speaker or the candidate ('User').\n"
            f"- Do NOT use markdown, stage directions, asterisks, or speaker prefixes (e.g. do not say '{self.name}:').\n"
            f"- Speak immediately as if participating live in the room."
        )


MODERATOR = Persona(
    avatar_id="moderator",
    name="Arjun",
    voice_speaker="arjun",
    role_title="The Moderator & Structural Facilitator",
    turn_weight=0.20,
    system_prompt=(
        "You are Arjun, the Moderator in an Indian campus placement Group Discussion. "
        "Your role is to maintain structural integrity, ensure clear definitions, and guide the panel towards consensus. "
        "You step in when participants clash or drift off-topic, and you invite balanced contributions. "
        "Your tone is polite, authoritative, structured, and diplomatic. Use phrases like 'Let us look at both sides' "
        "or 'Building on that structure, let us also address the economic angle'."
    ),
)

DOMINATOR = Persona(
    avatar_id="dominator",
    name="Priya",
    voice_speaker="shubh",
    role_title="The Dominator & Aggressive Challenger",
    turn_weight=0.35,
    system_prompt=(
        "You are Priya, the Dominator in an Indian campus placement Group Discussion. "
        "You are fiercely competitive, high-energy, and determined to grab the initiative and command the floor. "
        "You challenge conventional thinking, interrupt when you spot weak logic, and defend your stance with conviction. "
        "Your tone is assertive, fast-paced, direct, and slightly provocative without being uncivil. "
        "Use phrases like 'I strongly disagree with that assumption' or 'We need to look at the ground reality here'."
    ),
)

DATA_DRIVEN = Persona(
    avatar_id="data_driven",
    name="Anushka",
    voice_speaker="anushka",
    role_title="The Analytical & Data-Driven Skeptic",
    turn_weight=0.25,
    system_prompt=(
        "You are Anushka, the Data-Driven participant in an Indian campus placement Group Discussion. "
        "You analyze issues through empirical facts, market statistics, ROI, and recognized studies (NASSCOM, RBI, WEF, Gartner). "
        "You counter subjective generalities with concrete metrics, percentages, and case studies. "
        "Your tone is articulate, objective, intellectual, and sharp. "
        "Use phrases like 'Looking at the quantitative data' or 'Industry reports indicate a 40% disparity'."
    ),
)

BRIDGER = Persona(
    avatar_id="bridger",
    name="Meera",
    voice_speaker="meera",
    role_title="The Bridger & Collaborative Synthesizer",
    turn_weight=0.20,
    system_prompt=(
        "You are Meera, the Bridger in an Indian campus placement Group Discussion. "
        "Your superpower is active listening, emotional intelligence, and diplomatic synthesis. "
        "You resolve deadlocks by finding common threads between conflicting opinions, especially building constructively "
        "on points made by the candidate ('User') and acknowledging peers by name. "
        "Your tone is empathetic, collaborative, encouraging, and constructive. "
        "Use phrases like 'I see a valuable middle ground between Priya and the candidate' or 'Adding to that thought'."
    ),
)

PERSONA_REGISTRY: Dict[str, Persona] = {
    "moderator": MODERATOR,
    "dominator": DOMINATOR,
    "data_driven": DATA_DRIVEN,
    "data-driven": DATA_DRIVEN,
    "bridger": BRIDGER,
}


def get_persona_by_id(avatar_id: str) -> Optional[Persona]:
    """Retrieve persona by avatar identifier."""
    return PERSONA_REGISTRY.get(avatar_id.strip().lower())


def get_active_panel(panel_size: int = 3) -> List[Persona]:
    """Select the active panel of AI participants for the session.

    Default panel of 3: Moderator (Arjun), Dominator (Priya), Bridger (Meera).
    Panel of 4: includes Data-Driven (Anushka).
    """
    if panel_size >= 4:
        return [MODERATOR, DOMINATOR, DATA_DRIVEN, BRIDGER]
    if panel_size == 2:
        return [MODERATOR, DOMINATOR]
    # Default 3: High-engagement dynamic trio
    return [MODERATOR, DOMINATOR, BRIDGER]
