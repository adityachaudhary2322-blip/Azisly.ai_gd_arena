"""FastAPI server for GD Arena.

Exposes:
- WebSocket endpoint at `/ws/gd` strictly honoring SCHEMA.md.
- Health check endpoint at `/health`.
"""

import json
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.engine.gd_orchestrator import GDOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backend.main")

app = FastAPI(
    title="GD Arena API",
    description="Multi-agent Indian Campus Placement Group Discussion simulation engine",
    version="1.0.0",
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "mock_voice": settings.MOCK_VOICE,
        "port": settings.PORT,
    }


@app.websocket("/ws/gd")
async def websocket_gd_endpoint(websocket: WebSocket):
    """WebSocket endpoint for GD Arena real-time conversational session.

    Adheres strictly to the SCHEMA.md contract.
    """
    await websocket.accept()
    logger.info("WebSocket connection established on /ws/gd")

    async def send_json_message(payload: dict) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception as err:
            logger.debug("Failed sending payload to websocket: %s", err)

    orchestrator = GDOrchestrator(send_callback=send_json_message)

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                message = json.loads(raw_text)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received from client: %s", raw_text)
                continue

            await orchestrator.handle_client_message(message)

    except WebSocketDisconnect:
        logger.info("Client disconnected from /ws/gd")
    except Exception as exc:
        logger.error("Unhandled error in WebSocket handler: %s", exc)
    finally:
        await orchestrator.end_session()
