"""Category scores (0-10) and improvement advice for the post-GD report.

Delivery categories come from measured signals collected during the session
(speech duration, recognition, response timing). Content categories (logic,
knowledge) start from transcript heuristics and are refined by the LLM
evaluator when a live key is available.
"""

import re
from statistics import mean
from typing import Any, Dict, List, Optional

FILLERS = re.compile(
    r"\b(um+|uh+|erm|hmm+|like|basically|actually|literally|you know|i mean|sort of|kind of)\b",
    re.IGNORECASE,
)
CONNECTORS = re.compile(
    r"\b(because|therefore|so that|hence|thus|however|but|although|whereas|firstly|secondly|"
    r"finally|on the other hand|in conclusion|which means|as a result|for example|for instance|"
    r"kyunki|isliye|lekin|jabki|kyonki|इसलिए|लेकिन|क्योंकि)\b",
    re.IGNORECASE,
)
EXAMPLES = re.compile(r"\b(for example|for instance|such as|like when|e\.g\.|jaise|जैसे)\b", re.IGNORECASE)
BUILDING_ON = re.compile(
    r"\b(as you said|you mentioned|adding to|building on|i agree|i disagree|to add|"
    r"good point|your point|on that point|agree with|disagree with)\b",
    re.IGNORECASE,
)
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "should", "would", "will",
    "are", "is", "be", "of", "in", "on", "vs", "versus", "a", "an", "or", "to", "its", "it",
    "how", "what", "why", "does", "can", "still", "boon", "bane",
}

IDEAL_WPM = (110, 160)
# Pre-roll and trailing silence the client sends with each turn.
PADDING_SECONDS_PER_TURN = 0.8


def _clamp(x: float) -> float:
    return float(round(max(0.0, min(10.0, x)), 1))


def _stem(word: str) -> str:
    """Crude stem so 'markets' matches 'market' and 'regulated' matches 'regulation'."""
    return word[: max(4, len(word) - 3)]


def _words(text: str) -> List[str]:
    return re.findall(r"[\w']+", text.lower())


def compute_scores(
    transcripts: List[Dict[str, Any]],
    delivery: Optional[Dict[str, Any]] = None,
    topic: str = "",
    user_percent: int = 0,
) -> Dict[str, Any]:
    """Return {"scores", "overall_score", "strengths", "improvements", "delivery"}."""
    delivery = delivery or {}
    answers = [
        e.get("text", "").strip()
        for e in transcripts
        if e.get("speaker", "").lower() in ("user", "candidate") and e.get("text", "").strip()
    ]
    panel_names = {
        e.get("speaker", "")
        for e in transcripts
        if e.get("speaker", "").lower() not in ("user", "candidate")
    }

    if not answers:
        return _no_speech_report(delivery)

    all_text = " ".join(answers)
    words = _words(all_text)
    word_count = max(1, len(words))
    fillers = len(FILLERS.findall(all_text))
    fillers_per_100 = fillers / word_count * 100

    turns = int(delivery.get("turns") or 0)
    speech = float(delivery.get("speech_seconds") or 0.0) - PADDING_SECONDS_PER_TURN * turns
    wpm = round(word_count / (speech / 60)) if speech > 3 else None

    scores = []

    # Fluency: speaking pace and filler words.
    if wpm is None:
        pace = 7.5
        pace_note = "Pace not measured"
    elif wpm < IDEAL_WPM[0]:
        pace = 10 - (IDEAL_WPM[0] - wpm) / 8
        pace_note = f"About {wpm} words per minute, a little slow"
    elif wpm > IDEAL_WPM[1]:
        pace = 10 - (wpm - IDEAL_WPM[1]) / 8
        pace_note = f"About {wpm} words per minute, on the fast side"
    else:
        pace = 10
        pace_note = f"About {wpm} words per minute, a comfortable pace"
    fluency = _clamp(pace - fillers_per_100 * 0.8)
    scores.append(_score(
        "fluency", "Fluency", fluency,
        f"{pace_note}; {fillers} filler word{'s' if fillers != 1 else ''} ({fillers_per_100:.0f} per 100 words).",
        "Replace fillers like 'basically' and 'you know' with a short pause, and aim for 110-160 words per minute."
        if fluency < 8 else "Keep the steady pace; a deliberate pause before your key point adds weight.",
    ))

    # Accent & clarity: how reliably speech was understood (not accent preference).
    not_understood = int(delivery.get("not_understood") or 0)
    if turns:
        ratio = 1 - not_understood / turns
        clarity = _clamp(4 + 6 * ratio)
        clarity_note = (
            f"{turns - not_understood} of {turns} turns were understood clearly."
            " Rated on intelligibility, not on having any particular accent."
        )
    else:
        clarity = 7.0
        clarity_note = "Rated on intelligibility, not on having any particular accent."
    scores.append(_score(
        "clarity", "Accent & clarity", clarity, clarity_note,
        "Speak a touch slower, finish word endings, and keep the mic 15-20 cm from your mouth."
        if clarity < 8 else "Clear and easy to follow; keep projecting at the same volume.",
    ))

    # Logic & structure: reasoning connectors, developed answers, examples.
    connectors = len(CONNECTORS.findall(all_text))
    per_answer = connectors / len(answers)
    avg_len = word_count / len(answers)
    has_example = bool(EXAMPLES.search(all_text))
    logic = _clamp(
        3 + min(4.0, per_answer * 2)
        + (2 if avg_len >= 15 else 1 if avg_len >= 8 else 0)
        + (1 if has_example else 0)
    )
    scores.append(_score(
        "logic", "Logic & structure", logic,
        f"{connectors} reasoning link{'s' if connectors != 1 else ''} (because, however, therefore...) "
        f"across {len(answers)} answer{'s' if len(answers) != 1 else ''}, about {avg_len:.0f} words each.",
        "Use point, reason, example: state your view, say why ('because...'), then give one example."
        if logic < 8 else "Well reasoned; finish with a one-line conclusion to tie your point back to the topic.",
    ))

    # Knowledge & relevance: staying on the topic, and concrete specifics.
    topic_stems = {_stem(w) for w in _words(topic) if len(w) > 3 and w not in STOPWORDS}
    on_topic = (
        sum(1 for a in answers if any(w.startswith(t) for w in _words(a) for t in topic_stems))
        if topic_stems
        else len(answers)
    )
    specifics = len(re.findall(r"\d", all_text)) > 0
    named = len(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", all_text)) - len(answers)  # beyond sentence starts
    knowledge = _clamp(
        3 + 4 * (on_topic / len(answers)) + (1.5 if specifics else 0) + min(1.5, max(0, named) * 0.5)
    )
    scores.append(_score(
        "knowledge", "Knowledge & relevance", knowledge,
        f"{on_topic} of {len(answers)} answers tied directly to the topic"
        f"{'; used figures' if specifics else ''}.",
        "Bring one concrete fact, figure or real example into each answer, and name the topic explicitly."
        if knowledge < 8 else "Strong grasp; add a recent example or statistic to stand out further.",
    ))

    # Confidence & responsiveness: answering when asked, without long hesitation.
    questions = int(delivery.get("questions") or 0)
    answered = int(delivery.get("answered") or 0)
    check_ins = int(delivery.get("check_ins") or 0)
    delays = [float(d) for d in delivery.get("response_delays") or []]
    avg_delay = round(mean(delays), 1) if delays else None
    if questions:
        confidence = 10 * min(1.0, answered / questions)
        confidence -= max(0.0, (avg_delay or 0) - 2) * 1.0
        confidence -= check_ins * 1.0
        confidence = _clamp(confidence)
        conf_note = (
            f"Answered {answered} of {questions} question{'s' if questions != 1 else ''}"
            f"{f', starting after {avg_delay}s on average' if avg_delay is not None else ''}"
            f"{f'; needed {check_ins} check-in' + ('s' if check_ins != 1 else '') if check_ins else ''}."
        )
    else:
        confidence = 7.0
        conf_note = "Spoke when given the floor."
    scores.append(_score(
        "confidence", "Confidence & responsiveness", confidence, conf_note,
        "Start within two seconds of a question: open with 'I think...' while you gather the rest."
        if confidence < 8 else "Quick, assured responses; keep that energy through the closing minutes.",
    ))

    # Listening & engagement: building on others, balanced airtime.
    refs = len(BUILDING_ON.findall(all_text)) + sum(
        1 for n in panel_names if n and re.search(rf"\b{re.escape(n)}\b", all_text)
    )
    balance = 2 if 15 <= user_percent <= 40 else 1 if user_percent >= 8 else 0
    engagement = _clamp(4 + min(4, refs * 2) + balance)
    scores.append(_score(
        "engagement", "Listening & engagement", engagement,
        f"Referred to others' points {refs} time{'s' if refs != 1 else ''}; "
        f"you held {user_percent}% of the speaking time.",
        "Name the person you're responding to ('Building on Kabir's point...') before adding your view."
        if engagement < 8 else "Good listening; summarising two views before yours would show leadership.",
    ))

    overall = round(mean(s["score"] for s in scores), 1)
    ranked = sorted(scores, key=lambda s: s["score"])
    improvements = [s["tip"] for s in ranked if s["score"] < 8][:4]
    strengths = [f"{s['label']}: {s['summary']}" for s in ranked[::-1] if s["score"] >= 7.5][:3]
    if not improvements:
        improvements = [ranked[0]["tip"]]

    return {
        "scores": scores,
        "overall_score": overall,
        "strengths": strengths,
        "improvements": improvements,
        "delivery": {
            "words_per_minute": wpm,
            "filler_words": fillers,
            "avg_response_seconds": avg_delay,
            "questions_answered": answered,
            "questions_asked": questions,
        },
    }


def _score(key: str, label: str, score: float, summary: str, tip: str) -> Dict[str, Any]:
    return {"key": key, "label": label, "score": score, "summary": summary, "tip": tip}


def _no_speech_report(delivery: Dict[str, Any]) -> Dict[str, Any]:
    labels = [
        ("fluency", "Fluency"),
        ("clarity", "Accent & clarity"),
        ("logic", "Logic & structure"),
        ("knowledge", "Knowledge & relevance"),
        ("confidence", "Confidence & responsiveness"),
        ("engagement", "Listening & engagement"),
    ]
    scores = [
        _score(k, l, 0.0, "No speech was recorded, so this could not be assessed.",
               "Answer when a panelist turns to you with a question.")
        for k, l in labels
    ]
    return {
        "scores": scores,
        "overall_score": 0.0,
        "strengths": [],
        "improvements": [
            "Answer each time a panelist asks you a question; even a short view counts.",
            "Check your microphone is allowed and working before you start.",
            "Open with a simple stance ('I think...') and one reason, then build from there.",
        ],
        "delivery": {
            "words_per_minute": None,
            "filler_words": 0,
            "avg_response_seconds": None,
            "questions_answered": int(delivery.get("answered") or 0),
            "questions_asked": int(delivery.get("questions") or 0),
        },
    }


def merge_llm_judgement(result: Dict[str, Any], judgement: Dict[str, Any]) -> Dict[str, Any]:
    """Blend the LLM's logic/knowledge judgement and advice into the heuristic result."""
    by_key = {s["key"]: s for s in result["scores"]}
    for key in ("logic", "knowledge"):
        item = judgement.get(key)
        if not isinstance(item, dict) or key not in by_key:
            continue
        try:
            llm_score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        if 0 <= llm_score <= 10:
            # The LLM reads meaning; the heuristic reads structure. Weight meaning higher.
            by_key[key]["score"] = _clamp(0.7 * llm_score + 0.3 * by_key[key]["score"])
            reason = str(item.get("reason") or "").strip()
            if reason:
                by_key[key]["summary"] = reason
    tips = [str(t).strip() for t in judgement.get("improvements") or [] if str(t).strip()]
    if tips:
        result["improvements"] = (tips + result["improvements"])[:5]
    result["overall_score"] = round(mean(s["score"] for s in result["scores"]), 1)
    return result
