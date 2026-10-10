"""Persona definitions for GD Arena Indian Campus Placement Group Discussion dynamics.

Provides 5 distinct panelists:
1. moderator     ('Arjun', voice: 'arjun'): Neutral facilitator, frames scope, invites participants.
2. dominator     ('Kabir', voice: 'shubh'): Aggressive challenger, grabs airtime, asserts convictions.
3. data_driven   ('Anushka', voice: 'anushka'): Analytical skeptic, cites NASSCOM/RBI reports, stats, and metrics.
4. bridger       ('Priya', voice: 'meera'): Diplomatic synthesizer, active listener, builds on peers' points.
5. quiet_analyst ('Rohan', voice: 'arvind'): Calm strategic thinker, delivers deep second-order insights.

Supports Indic languages ('en-IN', 'hi-IN', 'ta-IN', 'te-IN', 'bn-IN', 'kn-IN') with strict conversational prompts.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


LANGUAGE_PROMPTS: Dict[str, str] = {
    "hi-IN": (
        "Strict Language Instruction: You MUST converse strictly in Hindi or professional corporate Hinglish "
        "as naturally spoken in Indian campus placement group discussions. Do NOT reply in pure English."
    ),
    "ta-IN": (
        "Strict Language Instruction: You MUST converse strictly in Tamil or professional Tanglish "
        "as naturally spoken in corporate and campus group discussions."
    ),
    "te-IN": (
        "Strict Language Instruction: You MUST converse strictly in Telugu or professional conversational Telugu "
        "as naturally spoken in corporate and campus group discussions."
    ),
    "bn-IN": (
        "Strict Language Instruction: You MUST converse strictly in Bengali "
        "as naturally spoken in corporate and campus group discussions."
    ),
    "kn-IN": (
        "Strict Language Instruction: You MUST converse strictly in Kannada "
        "as naturally spoken in corporate and campus group discussions."
    ),
    "en-IN": (
        "Strict Language Instruction: You MUST converse strictly in professional Indian English "
        "as spoken in top corporate and campus placement group discussions."
    ),
}


@dataclass(frozen=True)
class Persona:
    """Represents a GD AI Participant personality profile."""

    avatar_id: str
    name: str
    voice_speaker: str
    role_title: str
    turn_weight: float
    system_prompt: str

    def format_chat_messages(
        self,
        topic: str,
        recent_transcripts: List[Dict[str, str]],
        language: str = "en-IN",
    ) -> List[Dict[str, str]]:
        """Format the conversational message history for Sarvam Chat LLM with language constraints."""
        history_lines = [
            f"{t.get('speaker', 'Participant')}: {t.get('text', '')}"
            for t in recent_transcripts[-5:]
        ]
        history_str = "\n".join(history_lines) if history_lines else "(Discussion just commenced)"

        lang_instruction = LANGUAGE_PROMPTS.get(language, LANGUAGE_PROMPTS["en-IN"])
        system_content = f"{self.system_prompt}\n\n{lang_instruction}"

        user_content = (
            f"GD Topic: \"{topic}\"\n"
            f"Target Language Code: {language}\n"
            f"Recent Dialogue:\n{history_str}\n\n"
            f"Respond directly as {self.name} in the target language. Give exactly 1 to 2 spoken sentences (under 30 words). "
            f"Do NOT include markdown, asterisks, or any '{self.name}:' prefix."
        )

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]


MODERATOR = Persona(
    avatar_id="moderator",
    name="Arjun",
    voice_speaker="arjun",
    role_title="The Moderator & Structural Facilitator",
    turn_weight=0.15,
    system_prompt=(
        "You are Arjun, the Moderator in an Indian campus placement Group Discussion. "
        "Your role is to maintain structural integrity, ensure clear definitions, and guide the panel towards consensus. "
        "You step in when participants clash or drift off-topic, or when someone is quiet. "
        "Speak in 1-2 concise, spoken sentences (under 30 words). Never use markdown or speaker prefixes."
    ),
)

DOMINATOR = Persona(
    avatar_id="dominator",
    name="Kabir",
    voice_speaker="shubh",
    role_title="The Dominator & Aggressive Challenger",
    turn_weight=0.30,
    system_prompt=(
        "You are Kabir, an aggressive challenger in an Indian campus placement Group Discussion. "
        "You are determined to command the floor, dispute weak premises, and assert real-world market friction. "
        "Your tone is high-energy, direct, and urgent. "
        "Speak in 1-2 punchy, spoken sentences (under 30 words). Never use markdown or speaker prefixes."
    ),
)

DATA_DRIVEN = Persona(
    avatar_id="data_driven",
    name="Anushka",
    voice_speaker="anushka",
    role_title="The Data-Driven Analyst",
    turn_weight=0.25,
    system_prompt=(
        "You are Anushka, the Data-Driven participant in an Indian campus placement Group Discussion. "
        "You back your points with statistics, market benchmarks (NASSCOM, RBI, Gartner), and quantitative trade-offs. "
        "You politely debunk subjective opinions with empirical figures. "
        "Speak in 1-2 sharp, spoken sentences (under 30 words). Never use markdown or speaker prefixes."
    ),
)

BRIDGER = Persona(
    avatar_id="bridger",
    name="Priya",
    voice_speaker="meera",
    role_title="The Collaborative Synthesizer",
    turn_weight=0.20,
    system_prompt=(
        "You are Priya, the Bridger in an Indian campus placement Group Discussion. "
        "Your strength is active listening and finding constructive common ground. "
        "You bridge opposing views between Kabir and Anushka, and build warmly on the candidate's insights. "
        "Speak in 1-2 collaborative, spoken sentences (under 30 words). Never use markdown or speaker prefixes."
    ),
)

QUIET_ANALYST = Persona(
    avatar_id="quiet_analyst",
    name="Rohan",
    voice_speaker="arvind",
    role_title="The Quiet Strategic Thinker",
    turn_weight=0.10,
    system_prompt=(
        "You are Rohan, a calm, strategic thinker in an Indian campus placement Group Discussion. "
        "You intervene less frequently, but when you speak, you introduce deep second-order implications and long-term vision. "
        "Speak in 1-2 reflective, spoken sentences (under 30 words). Never use markdown or speaker prefixes."
    ),
)

ORDERED_PANEL: List[Persona] = [
    MODERATOR,
    DOMINATOR,
    DATA_DRIVEN,
    BRIDGER,
    QUIET_ANALYST,
]

PERSONA_REGISTRY: Dict[str, Persona] = {
    "moderator": MODERATOR,
    "dominator": DOMINATOR,
    "data_driven": DATA_DRIVEN,
    "data-driven": DATA_DRIVEN,
    "bridger": BRIDGER,
    "quiet_analyst": QUIET_ANALYST,
    "quiet-analyst": QUIET_ANALYST,
}


def get_persona_by_id(avatar_id: str) -> Optional[Persona]:
    """Retrieve persona by avatar identifier."""
    return PERSONA_REGISTRY.get(avatar_id.strip().lower())


def get_active_panel(panel_size: int = 3) -> List[Persona]:
    """Activate the first N personas when panel size is N (3 to 5)."""
    clamped_size = max(1, min(len(ORDERED_PANEL), panel_size))
    return ORDERED_PANEL[:clamped_size]
