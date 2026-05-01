from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from groq import Groq
import os
import uuid
import logging

# ── Load .env ─────────────────────────────────────────────────
load_dotenv()

# ── App Setup ─────────────────────────────────────────────────
app = Flask(__name__)

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── CORS ──────────────────────────────────────────────────────
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
CORS(app, origins=allowed_origins.split(","),
     supports_credentials=False,
     allow_headers=["Content-Type"],
     methods=["GET", "POST", "DELETE", "OPTIONS"])

# ── Env Config ────────────────────────────────────────────────
GROQ_API_KEY          = os.getenv("GROQ_API_KEY", "")
DEFAULT_MODEL         = os.getenv("DEFAULT_MODEL", "llama-3.3-70b-versatile")
MAX_TOKENS            = int(os.getenv("MAX_TOKENS", 1024))
DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful AI assistant. Be concise, clear, and friendly.")
FLASK_PORT            = int(os.getenv("FLASK_PORT", 5000))
FLASK_DEBUG           = os.getenv("FLASK_DEBUG", "False") == "True"

# ── In-memory conversation store ──────────────────────────────
# Structure: { session_id: { "history": [...], "system": "..." } }
conversations = {}

# ── Helper: get or create session ─────────────────────────────
def get_session(session_id):
    if session_id not in conversations:
        conversations[session_id] = {
            "history": [],
            "system": DEFAULT_SYSTEM_PROMPT
        }
    return conversations[session_id]

# ── Helper: resolve API key ────────────────────────────────────
def resolve_api_key(request_key):
    key = request_key or GROQ_API_KEY
    return key.strip() if key else None

# ══════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════

# ── GET / ──────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "Groq Agent API is running!",
        "endpoints": ["/health", "/chat", "/clear", "/history", "/sessions"]
    })

# ── POST /chat ─────────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body."}), 400

    request_key   = data.get("api_key", "")
    user_message  = data.get("message", "").strip()
    session_id    = data.get("session_id") or str(uuid.uuid4())
    system_prompt = data.get("system_prompt", "").strip()

    api_key = resolve_api_key(request_key)
    if not api_key:
        return jsonify({"error": "API key is required. Set GROQ_API_KEY in .env or pass it in the request."}), 400

    if not user_message:
        return jsonify({"error": "Message cannot be empty."}), 400

    session = get_session(session_id)

    if system_prompt:
        session["system"] = system_prompt

    session["history"].append({
        "role": "user",
        "content": user_message
    })

    logger.info(f"Session [{session_id}] — User: {user_message[:60]}...")

    try:
        client = Groq(api_key=api_key)

        # Groq uses OpenAI-style messages with system injected as first message
        messages = [{"role": "system", "content": session["system"]}] + session["history"]

        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            max_tokens=MAX_TOKENS,
            messages=messages
        )

        assistant_reply = response.choices[0].message.content

        session["history"].append({
            "role": "assistant",
            "content": assistant_reply
        })

        logger.info(f"Session [{session_id}] — Assistant replied ({len(assistant_reply)} chars)")

        return jsonify({
            "reply":         assistant_reply,
            "session_id":    session_id,
            "model":         response.model,
            "turns":         len(session["history"]) // 2,
            "input_tokens":  response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        })

    except Exception as e:
        error_str = str(e)
        session["history"].pop()  # Remove unanswered user message

        if "401" in error_str or "invalid_api_key" in error_str.lower() or "authentication" in error_str.lower():
            logger.warning(f"Session [{session_id}] — Authentication failed.")
            return jsonify({"error": "Invalid API key. Please check your Groq key and try again."}), 401

        elif "429" in error_str or "rate_limit" in error_str.lower():
            logger.warning(f"Session [{session_id}] — Rate limit hit.")
            return jsonify({"error": "Rate limit exceeded. Please wait a moment and try again."}), 429

        elif "400" in error_str:
            logger.error(f"Session [{session_id}] — Bad request: {e}")
            return jsonify({"error": f"Bad request: {error_str}"}), 400

        elif "connection" in error_str.lower() or "network" in error_str.lower():
            logger.error(f"Session [{session_id}] — Connection error.")
            return jsonify({"error": "Could not connect to Groq API. Check your internet connection."}), 503

        else:
            logger.error(f"Session [{session_id}] — Unexpected error: {e}")
            return jsonify({"error": f"Unexpected error: {error_str}"}), 500


# ── POST /clear ────────────────────────────────────────────────
@app.route("/clear", methods=["POST"])
def clear():
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id is required."}), 400

    removed = conversations.pop(session_id, None)
    if removed:
        logger.info(f"Session [{session_id}] — Cleared ({len(removed['history'])} messages).")
        return jsonify({"message": "Conversation cleared.", "session_id": session_id})
    else:
        return jsonify({"message": "Session not found (already empty).", "session_id": session_id})


# ── GET /history ───────────────────────────────────────────────
@app.route("/history", methods=["GET"])
def history():
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id query param is required."}), 400

    session = conversations.get(session_id)
    if not session:
        return jsonify({"session_id": session_id, "history": [], "turns": 0})

    return jsonify({
        "session_id": session_id,
        "history":    session["history"],
        "turns":      len(session["history"]) // 2,
        "system":     session["system"]
    })


# ── GET /sessions ──────────────────────────────────────────────
@app.route("/sessions", methods=["GET"])
def sessions():
    summary = [
        {
            "session_id": sid,
            "turns":      len(data["history"]) // 2,
            "system":     data["system"][:60] + "..." if len(data["system"]) > 60 else data["system"]
        }
        for sid, data in conversations.items()
    ]
    return jsonify({"active_sessions": len(summary), "sessions": summary})


# ── DELETE /session ────────────────────────────────────────────
@app.route("/session", methods=["DELETE"])
def delete_session():
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id is required."}), 400

    conversations.pop(session_id, None)
    return jsonify({"message": f"Session {session_id} deleted."})


# ── GET /health ────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":          "ok",
        "model":           DEFAULT_MODEL,
        "max_tokens":      MAX_TOKENS,
        "active_sessions": len(conversations),
        "api_key_loaded":  bool(GROQ_API_KEY)
    })


# ══════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logger.info(f"Starting Groq Agent Server on port {FLASK_PORT}")
    logger.info(f"Model: {DEFAULT_MODEL} | Max Tokens: {MAX_TOKENS}")
    logger.info(f"API Key from .env: {'✓ Loaded' if GROQ_API_KEY else '✗ Not set (must pass in request)'}")
    app.run(debug=FLASK_DEBUG, port=FLASK_PORT)