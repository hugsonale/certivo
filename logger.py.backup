# logger.py
import logging
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO)

def log_event(event, session_id, challenge_id=None, details=None):
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event,
        "session_id": session_id,
        "challenge_id": challenge_id,
        "details": details or {}
    }
    logging.info(json.dumps(payload))
