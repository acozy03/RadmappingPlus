# chat.py  — minimal "push to n8n" endpoint

from flask import Blueprint, request, jsonify
import os
import requests
import uuid
from datetime import datetime
chat_bp = Blueprint("chat", __name__)

# Required: set this env var to your n8n Webhook (Production URL)
#   export N8N_WEBHOOK_URL="https://<n8n-host>/webhook/<id>"
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "").strip()
print(f"N8N_WEBHOOK_URL set to: {N8N_WEBHOOK_URL[:40]}...")
# Optional: simple shared secret (set in both Flask and n8n and check the header)
#   export N8N_WEBHOOK_SECRET="something-long-and-random"
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET", "").strip()

# chat.py
def forward_to_n8n(payload: dict) -> tuple[bool, dict | None, str]:
    if not N8N_WEBHOOK_URL:
        return False, None, "N8N_WEBHOOK_URL not configured"
    headers = {"Content-Type": "application/json"}
    if N8N_WEBHOOK_SECRET:
        headers["x-n8n-secret"] = N8N_WEBHOOK_SECRET
    try:
        r = requests.post(N8N_WEBHOOK_URL, json=payload, headers=headers, timeout=30)
        if 200 <= r.status_code < 300:
            # assume n8n responded with JSON
            try:
                return True, r.json(), ""
            except Exception:
                return False, None, f"n8n returned non-JSON: {r.text[:200]}"
        return False, None, f"n8n {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, None, str(e)


@chat_bp.route("/chat/history", methods=["GET"])
def chat_history():
    # minimal placeholder
    return jsonify({"history": []}), 200


@chat_bp.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Missing 'question'"}), 400

    payload = {
        "question": question,
        "user_id": (data.get("user_id") or "").strip() or None,
        "request_id": str(uuid.uuid4()),
        "received_at": datetime.utcnow().isoformat() + "Z",
        "source": "flask-app",
        "fast": True,
        "slow": False,
        "radmapping": True,
        "ip": request.headers.get("x-forwarded-for", request.remote_addr),
        "user_agent": request.headers.get("user-agent", ""),
    }

    ok, body, err = forward_to_n8n(payload)
    if not ok:
        return jsonify({"error": f"Failed to call n8n: {err}"}), 502

    print(f"n8n response: {body}")
    # body should look like { response: "...", sql_query: "..." }
    return jsonify(body), 200

    



