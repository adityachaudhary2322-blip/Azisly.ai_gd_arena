"""Integration tests for FastAPI WebSocket endpoint /ws/gd against SCHEMA.md."""

import json
import pytest
from fastapi.testclient import TestClient
from backend.main import app


def test_health_endpoint():
    """Verify health endpoint responds with 200 and valid JSON."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
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
        for _ in range(5):
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
