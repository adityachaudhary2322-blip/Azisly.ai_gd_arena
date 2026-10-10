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


# Further mock lines so a mock-mode discussion does not repeat itself every turn.
MOCK_EXTRA_DIALOGUE_EN: Dict[str, List[str]] = {
    "moderator": [
        "We have two clear camps forming here, so let's test where they actually disagree.",
        "Let's bring this back to the core question and look at who bears the cost.",
    ],
    "dominator": [
        "Honestly, that sounds nice on paper, but companies won't wait for anyone to catch up.",
        "I'll push back again, because playing safe is exactly how firms lose the market.",
    ],
    "data_driven": [
        "The numbers tell a more nuanced story; reskilling programs show around 60% placement rates.",
        "If we look at five-year trends, adoption is fastest exactly where wages are highest.",
    ],
    "bridger": [
        "Both of you are right in parts, and the overlap is really about timing.",
        "Maybe the real answer combines Kabir's urgency with Anushka's evidence on transitions.",
    ],
    "quiet_analyst": [
        "The second-order effect matters more: who trains the next generation if entry roles vanish?",
        "In ten years the question won't be jobs lost, but which skills compound in value.",
    ],
}

MOCK_EXTRA_DIALOGUE_HI: Dict[str, List[str]] = {
    "moderator": ["Chaliye dekhte hain ki asli disagreement kahan hai."],
    "dominator": ["Sach kahun toh companies kisi ka intezaar nahi karengi."],
    "data_driven": ["Data dikhata hai ki reskilling programs mein lagbhag 60% placement hota hai."],
    "bridger": ["Aap dono kuch had tak sahi hain, asli sawaal timing ka hai."],
    "quiet_analyst": ["Lambi avadhi mein sawaal yeh hoga ki kaunse skills ki value badhegi."],
}

MOCK_INVITE_EN: Dict[str, str] = {
    "moderator": "We haven't heard from you yet. What's your view on the biggest risk here?",
    "dominator": "So tell me, do you really think caution wins in a market moving this fast?",
    "data_driven": "Which data point would change your mind on this, if any?",
    "bridger": "You've been listening closely. Where do you see the middle ground?",
    "quiet_analyst": "Looking five years ahead, what do you think matters most here?",
}

MOCK_INVITE_HI: Dict[str, str] = {
    "moderator": "Humne abhi tak aapki raay nahi suni. Aapke hisaab se sabse bada risk kya hai?",
    "dominator": "Toh aap batayiye, kya itni tez market mein caution kaam karega?",
    "data_driven": "Kaunsa data aapki raay badal sakta hai?",
    "bridger": "Aapke hisaab se middle ground kya ho sakta hai?",
    "quiet_analyst": "Paanch saal aage dekhein toh aapko kya sabse zaroori lagta hai?",
}

MOCK_REACT_EN: Dict[str, str] = {
    "moderator": "That's a useful framing, and it shifts the focus to execution.",
    "dominator": "I'd challenge that, because markets rarely reward waiting it out.",
    "data_driven": "That lines up with the data, though the effect varies a lot by sector.",
    "bridger": "I like that, and it connects nicely with what Kabir said earlier.",
    "quiet_analyst": "That raises a deeper question about who adapts and who gets left behind.",
}

MOCK_REACT_HI: Dict[str, str] = {
    "moderator": "Yeh ek accha framing hai, isse focus execution par aata hai.",
    "dominator": "Main isse challenge karunga, market kabhi intezaar ko reward nahi karti.",
    "data_driven": "Yeh data se match karta hai, lekin har sector mein farak hai.",
    "bridger": "Mujhe yeh pasand aaya, yeh Kabir ki baat se bhi judta hai.",
    "quiet_analyst": "Isse ek gehra sawaal uthta hai ki kaun adapt karega.",
}

MOCK_SUMMARY_EN = (
    "Let me sum up today. We weighed speed against caution, looked at the data on reskilling, "
    "and you added a clear perspective of your own. Thank you all, and we'll continue another day."
)
MOCK_SUMMARY_HI = (
    "Aaj ki charcha ka saar yeh hai ki humne speed aur caution dono par baat ki, data dekha, "
    "aur aapne apna spasht nazariya rakha. Aap sabhi ka dhanyavaad, hum kisi aur din aage badhenge."
)

_PERSONA_KEYS = (
    ("moderator", ("arjun", "moderator")),
    ("dominator", ("kabir", "dominator")),
    ("data_driven", ("anushka", "data_driven", "data-driven")),
    ("bridger", ("priya", "bridger")),
    ("quiet_analyst", ("rohan", "quiet_analyst", "quiet analyst")),
)


def _match_persona(text: str) -> Optional[str]:
    for key, needles in _PERSONA_KEYS:
        if any(n in text for n in needles):
            return key
    return None


def _history_length(user_text: str) -> int:
    """Count dialogue lines in the prompt; used to vary mock lines deterministically."""
    if "recent dialogue:" not in user_text:
        return 0
    block = user_text.split("recent dialogue:", 1)[1].split("\n\n", 1)[0]
    return sum(1 for line in block.splitlines() if ":" in line)


# Topic-templated mock lines, so mock-mode discussions stay on whatever topic was chosen.
MOCK_TOPIC_DIALOGUE_EN: Dict[str, List[str]] = {
    "moderator": [
        "Let's look at {topic} from two sides: who benefits, and who bears the cost.",
        "We have different views on {topic}; let's pin down exactly where we disagree.",
    ],
    "dominator": [
        "I'll be direct: on {topic}, the popular view is too comfortable and ignores the hard realities.",
        "Honestly, when it comes to {topic}, waiting and watching is the worst option we have.",
    ],
    "data_driven": [
        "If we look at the evidence on {topic}, the picture is more mixed than either side admits.",
        "On {topic}, the measurable outcomes matter more than opinions, and they point both ways.",
    ],
    "bridger": [
        "I think both views on {topic} share a common goal, and that's where we can build.",
        "There's a middle ground on {topic} if we combine the urgency with the evidence.",
    ],
    "quiet_analyst": [
        "The deeper question about {topic} is what it changes over the next ten years.",
        "Beyond the immediate debate, {topic} has second-order effects we haven't discussed.",
    ],
}
MOCK_TOPIC_DIALOGUE_HI: Dict[str, List[str]] = {
    "moderator": ["Chaliye {topic} ko dono pehluon se dekhte hain: kise fayda hai aur kise nuksaan."],
    "dominator": ["Seedhi baat, {topic} par aam raay bahut aaram-pasand hai aur zameeni sach ko nazarandaz karti hai."],
    "data_driven": ["{topic} ke saboot dekhein toh tasveer dono taraf ki raay se zyada mili-juli hai."],
    "bridger": ["Mujhe lagta hai {topic} par dono vichaaron ka lakshya ek hi hai, wahin se aage badh sakte hain."],
    "quiet_analyst": ["{topic} ka gehra sawaal yeh hai ki agle das saal mein yeh kya badlega."],
}
MOCK_TOPIC_INVITE_EN = "What's your own view on {topic}, and why?"
MOCK_TOPIC_INVITE_HI = "{topic} par aapki apni raay kya hai, aur kyon?"
MOCK_TOPIC_REACT_EN = "That's a fair point on {topic}, and it changes how we should weigh the trade-offs."
MOCK_TOPIC_REACT_HI = "{topic} par yeh accha point hai, isse trade-offs ko dekhne ka nazariya badalta hai."


def _prompt_topic(user_text: str) -> Optional[str]:
    marker = 'gd topic: "'
    if marker not in user_text:
        return None
    return user_text.split(marker, 1)[1].split('"', 1)[0].strip() or None


def _detect_mock_response(messages: List[Dict[str, str]]) -> str:
    """Select appropriate deterministic mock text based on message contents and target language."""
    full_text = " ".join(m.get("content", "") for m in messages).lower()

    # Check if request is for evaluation or JSON schema report
    if "final_report" in full_text or "evaluat" in full_text or "json" in full_text:
        return json.dumps(MOCK_EVALUATION_REPORT)

    # Determine dialogue bank based on language indicator
    is_hindi = "hi-in" in full_text or "hindi" in full_text or "hinglish" in full_text
    dialogues = MOCK_PERSONA_DIALOGUE_HI if is_hindi else MOCK_PERSONA_DIALOGUE_EN
    extras = MOCK_EXTRA_DIALOGUE_HI if is_hindi else MOCK_EXTRA_DIALOGUE_EN

    # Identify the speaker from the system prompt first: the dialogue history
    # mentions every panelist's name, so searching it would pick the wrong one.
    system_text = " ".join(m.get("content", "") for m in messages if m.get("role") == "system").lower()
    user_text = " ".join(m.get("content", "") for m in messages if m.get("role") != "system").lower()
    persona = _match_persona(system_text) or _match_persona(full_text)
    if persona is None:
        return MOCK_DEFAULT_REPLY

    # Keep the original casing of the topic for the spoken line.
    raw_user = " ".join(m.get("content", "") for m in messages if m.get("role") != "system")
    topic = _prompt_topic(raw_user.lower()) and raw_user.split('GD Topic: "', 1)[-1].split('"', 1)[0]

    if "ask the candidate" in user_text:
        if topic:
            return (MOCK_TOPIC_INVITE_HI if is_hindi else MOCK_TOPIC_INVITE_EN).format(topic=topic)
        return (MOCK_INVITE_HI if is_hindi else MOCK_INVITE_EN)[persona]
    if "the candidate just spoke" in user_text:
        if topic:
            return (MOCK_TOPIC_REACT_HI if is_hindi else MOCK_TOPIC_REACT_EN).format(topic=topic)
        return (MOCK_REACT_HI if is_hindi else MOCK_REACT_EN)[persona]

    if topic:
        bank = (MOCK_TOPIC_DIALOGUE_HI if is_hindi else MOCK_TOPIC_DIALOGUE_EN)[persona]
        return bank[_history_length(user_text) % len(bank)].format(topic=topic)

    bank = [dialogues[persona], *extras.get(persona, [])]
    return bank[_history_length(user_text) % len(bank)]


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
