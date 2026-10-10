"""Integration tests for FastAPI WebSocket endpoint /ws/gd against SCHEMA.md."""

import json
import pytest
from fastapi.testclient import TestClient
from backend.main import app


def test_root_endpoint():
    """Verify root endpoint responds with 200 and valid status JSON."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["service"] == "gd-arena-backend"
    assert "health" in data
    assert "websocket" in data


def test_health_endpoint():
    """Verify health endpoint responds with 200 and valid JSON."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "gd-arena-backend"
    assert "mock_voice" in data


def test_websocket_gd_session_flow():
    """Verify WebSocket /ws/gd end-to-end communication adhering to SCHEMA.md."""
    client = TestClient(app)

    with client.websocket_connect("/ws/gd") as websocket:
        # 1. Send start_session
        start_payload = {
            "type": "start_session",
            "topic": "AI in Job Markets",
            "panel_size": 3,
            "language": "en-IN",
        }
        websocket.send_text(json.dumps(start_payload))

        # 2. Collect initial messages (timer_tick, transcript_update, agent_speaking)
        received_types = set()
        for _ in range(3):
            data = websocket.receive_text()
            msg = json.loads(data)
            received_types.add(msg.get("type"))

        assert "transcript_update" in received_types or "timer_tick" in received_types

        # 3. Send user_interrupted
        websocket.send_text(json.dumps({"type": "user_interrupted"}))

        # 4. Send end_session
        websocket.send_text(json.dumps({"type": "end_session"}))

        # 5. Receive until final_report is caught
        final_report_found = False
        for _ in range(40):
            try:
                data = websocket.receive_text()
                msg = json.loads(data)
                if msg.get("type") == "final_report":
                    final_report_found = True
                    metrics = msg.get("metrics", {})
                    assert "speaking_time_user_percent" in metrics
                    assert "interruptions_handled" in metrics
                    assert "initiative_score" in metrics
                    assert isinstance(msg.get("feedback"), list)
                    break
            except Exception:
                break

        assert final_report_found is True


def test_websocket_indic_language_start_session():
    """Verify WebSocket /ws/gd successfully accepts start_session with Indic language code."""
    client = TestClient(app)

    with client.websocket_connect("/ws/gd") as websocket:
        websocket.send_text(json.dumps({
            "type": "start_session",
            "topic": "Campus Hiring Trends",
            "panel_size": 4,
            "language": "hi-IN",
        }))

        # Collect initial messages
        first_msg = json.loads(websocket.receive_text())
        assert first_msg.get("type") in ("timer_tick", "transcript_update", "agent_speaking")

        websocket.send_text(json.dumps({"type": "end_session"}))

