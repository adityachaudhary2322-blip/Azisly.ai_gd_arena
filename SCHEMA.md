# GD Arena WebSocket & State Contract

## Client -> Server Messages
- Start Session:
  {"type": "start_session", "topic": "AI in Job Markets", "panel_size": 3, "language": "en-IN"}
- Audio Stream Chunk:
  {"type": "audio_chunk", "data": "<base64_encoded_audio>"}
- User Interrupted AI:
  {"type": "user_interrupted"}
- End Session Early:
  {"type": "end_session"}

## Server -> Client Messages
- Live Transcript Append:
  {"type": "transcript_update", "speaker": "User" | "Arjun" | "Priya", "text": "I disagree with...", "timestamp": 12.4}
- Agent Begins Speaking:
  {"type": "agent_speaking", "speaker": "Priya", "avatar_id": "dominator", "audio_base64": "<base64_wav_or_mp3>"}
- Agent Was Cut Off:
  {"type": "agent_interrupted", "speaker": "Priya"}
- Timer Heartbeat:
  {"type": "timer_tick", "seconds_left": 420}
- Final Post-GD Evaluation:
  {
    "type": "final_report",
    "metrics": {
      "speaking_time_user_percent": 24,
      "interruptions_handled": 3,
      "initiative_score": 8
    },
    "feedback": [
      {
        "criterion": "Idea Building",
        "quote": "Adding to Priya's point regarding regulation...",
        "analysis": "Strong collaborative phrasing; bridged between two divergent viewpoints."
      }
    ]
  }
