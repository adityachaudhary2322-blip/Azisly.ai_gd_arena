"""Tests for post-GD session evaluator engine."""

import pytest
from backend.engine.evaluator import calculate_speaking_metrics, evaluate_session


def test_speaking_metrics_calculation():
    """Verify speaking percentage and initiative scoring."""
    sample_transcript = [
        {"speaker": "Arjun", "text": "Welcome to the group discussion on AI.", "timestamp": 1.0},
        {"speaker": "User", "text": "I believe artificial intelligence creates more high-skill opportunities.", "timestamp": 5.0},
        {"speaker": "Priya", "text": "I disagree with that optimistic view entirely.", "timestamp": 12.0},
        {"speaker": "User", "text": "Let me clarify with historical precedent from the industrial revolution.", "timestamp": 18.0},
    ]

    metrics = calculate_speaking_metrics(sample_transcript, interruptions_count=2)

    assert metrics["speaking_time_user_percent"] > 0
    assert metrics["speaking_time_user_percent"] <= 100
    assert metrics["interruptions_handled"] == 2
    assert 1 <= metrics["initiative_score"] <= 10


@pytest.mark.asyncio
async def test_evaluate_session_schema_compliance():
    """Verify that evaluate_session returns structure strictly adhering to SCHEMA.md."""
    sample_transcript = [
        {"speaker": "Arjun", "text": "Welcome everyone.", "timestamp": 1.0},
        {"speaker": "User", "text": "Adding to Priya's point regarding regulation, ethical governance is essential.", "timestamp": 8.0},
        {"speaker": "Priya", "text": "Regulation slows down innovation.", "timestamp": 14.0},
    ]

    report = await evaluate_session(sample_transcript, interruptions_count=1)

    assert report["type"] == "final_report"
    assert "metrics" in report
    assert "feedback" in report

    # Check metrics keys
    metrics = report["metrics"]
    assert "speaking_time_user_percent" in metrics
    assert "interruptions_handled" in metrics
    assert "initiative_score" in metrics

    # Check feedback items format
    feedback = report["feedback"]
    assert len(feedback) > 0
    for item in feedback:
        assert "criterion" in item
        assert "quote" in item
        assert "analysis" in item
        assert len(item["quote"]) > 0
        assert len(item["analysis"]) > 0

    # Ensure verbatim quote appears in feedback
    quotes = [f["quote"] for f in feedback]
    assert any("Adding to Priya's point" in q for q in quotes)
