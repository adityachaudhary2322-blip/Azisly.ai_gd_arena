# GD Arena WebSocket & State Contract

## Client -> Server Messages
- Start Session:
  {"type": "start_session", "topic": "AI in Job Markets", "panel_size": 3, "language": "en-IN",
   "profile": {"field": "Backend engineering", "interests": "Kafka, system design"}}
  (language "hi-IN" = Hindi + English / Hinglish. profile is optional and tailors the panel's questions.)
- Audio Stream Chunk:
  {"type": "audio_chunk", "data": "<base64_encoded_audio>"}
  (16-bit PCM, 16 kHz mono, 100 ms per chunk. Sent only while the candidate holds the floor and is speaking, gated by client-side VAD with ~300 ms pre-roll; the server treats every chunk as speech and ignores audio while the panel holds the floor.)
- Clip Finished Playing:
  {"type": "playback_finished", "turn_id": 7}
- User Interrupted AI (legacy; the current client waits to be handed the floor):
  {"type": "user_interrupted"}
- End Session Early:
  {"type": "end_session"}

## Server -> Client Messages
- Live Transcript Append:
  {"type": "transcript_update", "speaker": "User" | "<panelist name>", "text": "I disagree with...", "timestamp": 12.4, "turn_id": 7}
  (turn_id pairs a panelist line with its agent_speaking clip; absent for "User".)
- Agent Begins Speaking:
  {"type": "agent_speaking", "speaker": "Kabir", "avatar_id": "dominator", "audio_base64": "<base64_wav_or_mp3>",
   "turn_id": 7, "text": "So tell me...", "yields_floor": true}
  (avatar_id: moderator | dominator | data_driven | bridger | quiet_analyst. yields_floor: the clip ends with a question to the candidate.)
- Floor Changed:
  {"type": "turn_update", "floor": "user" | "panel", "speaker": "Kabir"}
  (floor "user": the candidate may answer the speaker's question. No reply within 1.5 s -> the asker checks in; asking to repeat replays the question; asking to stop for today -> the moderator summarizes and final_report follows.)
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
      "initiative_score": 8,
      "speaking_time_distribution": {"User": 24, "Arjun": 20, "Kabir": 24, "Anushka": 18, "Priya": 14}
    },
    "feedback": [
      {
        "criterion": "Idea Building",
        "quote": "Adding to Priya's point regarding regulation...",
        "analysis": "Strong collaborative phrasing; bridged between two divergent viewpoints."
      }
    ]
  }
