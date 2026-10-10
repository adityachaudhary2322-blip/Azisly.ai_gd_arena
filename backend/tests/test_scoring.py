"""Tests for the per-category report scores and improvement advice."""

import pytest

from backend.engine.evaluator import evaluate_session
from backend.engine.scoring import compute_scores, merge_llm_judgement

KEYS = ["fluency", "clarity", "logic", "knowledge", "confidence", "engagement"]


def _session(*answers):
    transcript = [{"speaker": "Arjun", "text": "Welcome to the discussion on remote work.", "timestamp": 0.0}]
    for a in answers:
        transcript.append({"speaker": "Kabir", "text": "What do you think about this?", "timestamp": 1.0})
        transcript.append({"speaker": "User", "text": a, "timestamp": 2.0})
    return transcript


def test_strong_answers_outscore_weak_ones():
    strong = _session(
        "I think remote work helps productivity because people save two hours of commuting; "
        "for example, a 2023 Stanford study found a 13% gain. However, building on Kabir's point, "
        "collaboration suffers, so a hybrid model works best.",
    )
    weak = _session("Um, basically, like, you know, it is, um, basically fine I guess.")
    delivery = {"questions": 1, "answered": 1, "turns": 1, "speech_seconds": 18.0, "response_delays": [1.0]}

    good = compute_scores(strong, delivery, topic="Remote work", user_percent=30)
    bad = compute_scores(weak, {**delivery, "speech_seconds": 6.0, "response_delays": [4.5]},
                         topic="Remote work", user_percent=5)

    assert [s["key"] for s in good["scores"]] == KEYS
    by = lambda r: {s["key"]: s["score"] for s in r["scores"]}
    g, b = by(good), by(bad)
    for key in ("fluency", "logic", "knowledge", "confidence", "engagement"):
        assert g[key] > b[key], key
    assert good["overall_score"] > bad["overall_score"]
    assert all(0 <= s["score"] <= 10 for s in good["scores"] + bad["scores"])
    assert bad["improvements"] and any("filler" in t.lower() for t in bad["improvements"])


def test_clarity_reflects_unrecognised_turns():
    delivery = {"questions": 2, "answered": 1, "turns": 2, "not_understood": 1, "speech_seconds": 10.0}
    result = compute_scores(_session("Remote work saves time."), delivery, topic="Remote work")
    clarity = next(s for s in result["scores"] if s["key"] == "clarity")
    assert clarity["score"] == 7.0
    assert "not on having any particular accent" in clarity["summary"]


def test_no_speech_scores_zero_with_advice():
    result = compute_scores([{"speaker": "Arjun", "text": "Welcome.", "timestamp": 0}], {"questions": 2})
    assert result["overall_score"] == 0.0
    assert all(s["score"] == 0.0 for s in result["scores"])
    assert len(result["improvements"]) == 3


def test_llm_judgement_refines_logic_and_knowledge():
    base = compute_scores(_session("Remote work is good."), {}, topic="Remote work")
    merged = merge_llm_judgement(base, {
        "logic": {"score": 9, "reason": "Clear claim with a supporting reason."},
        "knowledge": {"score": "not a number"},
        "improvements": ["Cite one study."],
    })
    logic = next(s for s in merged["scores"] if s["key"] == "logic")
    assert logic["summary"] == "Clear claim with a supporting reason."
    assert merged["improvements"][0] == "Cite one study."


@pytest.mark.asyncio
async def test_final_report_carries_scores_and_delivery():
    report = await evaluate_session(
        _session("Remote work saves commuting time because offices are far."),
        delivery={"questions": 1, "answered": 1, "turns": 1, "speech_seconds": 6.0, "response_delays": [1.2]},
        topic="Remote work",
    )
    assert report["type"] == "final_report"
    assert [s["key"] for s in report["scores"]] == KEYS
    assert 0 < report["overall_score"] <= 10
    assert report["delivery"]["questions_answered"] == 1
    assert report["improvements"]


def test_topic_match_tolerates_word_forms():
    result = compute_scores(
        _session("Job markets will shift as automation grows."), {}, topic="AI in Job Markets"
    )
    knowledge = next(s for s in result["scores"] if s["key"] == "knowledge")
    assert knowledge["summary"].startswith("1 of 1 answers")
    assert all(isinstance(s["score"], float) for s in result["scores"])
