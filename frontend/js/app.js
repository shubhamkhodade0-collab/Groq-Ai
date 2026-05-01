// ── Config ───────────────────────────────────────────────────
// NEW — works both locally and on Render
const API_URL = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
  ? "http://localhost:5000"
  : "https://your-backend-name.onrender.com";  // ← replace with your Render backend URL
const SESSION_ID = "session_" + Math.random().toString(36).slice(2, 9);

// ── DOM refs ─────────────────────────────────────────────────
const systemPromptEl = document.getElementById("systemPrompt");
const clearBtn       = document.getElementById("clearBtn");
const messagesEl     = document.getElementById("messages");
const userInputEl    = document.getElementById("userInput");
const sendBtn        = document.getElementById("sendBtn");
const statusDot      = document.getElementById("statusDot");
const statusText     = document.getElementById("statusText");

// ── Status helpers ───────────────────────────────────────────
function setStatus(state, label) {
  statusDot.className = "status-dot " + state;
  statusText.textContent = label;
}

// ── Auto-resize textarea ──────────────────────────────────────
userInputEl.addEventListener("input", () => {
  userInputEl.style.height = "auto";
  userInputEl.style.height = Math.min(userInputEl.scrollHeight, 140) + "px";
});

// ── Send on Enter (Shift+Enter = newline) ─────────────────────
userInputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener("click", sendMessage);
clearBtn.addEventListener("click", clearChat);

// ── Append message bubble ─────────────────────────────────────
function appendMessage(role, content) {
  // Remove welcome screen on first message
  const welcome = messagesEl.querySelector(".welcome");
  if (welcome) welcome.remove();

  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "You" : "⬡";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  // Render newlines + basic code blocks
  bubble.innerHTML = formatContent(content);

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

// ── Thinking indicator ────────────────────────────────────────
function showThinking() {
  const wrap = document.createElement("div");
  wrap.className = "message bot";
  wrap.id = "thinking";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "⬡";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = `<div class="thinking"><span></span><span></span><span></span></div>`;

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeThinking() {
  const t = document.getElementById("thinking");
  if (t) t.remove();
}

// ── Format message content ────────────────────────────────────
function formatContent(text) {
  // Escape HTML
  let safe = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Code blocks
  safe = safe.replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>");
  // Inline code
  safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");
  // Newlines
  safe = safe.replace(/\n/g, "<br/>");
  return safe;
}

// ── Main send function ────────────────────────────────────────
async function sendMessage() {
  const message = userInputEl.value.trim();
  const system  = systemPromptEl.value.trim();
  if (!message) return;

  // Clear input
  userInputEl.value = "";
  userInputEl.style.height = "auto";

  appendMessage("user", message);
  showThinking();
  sendBtn.disabled = true;
  setStatus("loading", "Thinking…");

  try {
    const res = await fetch(`${API_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
      message:       message,
      session_id:    SESSION_ID,
      system_prompt: system
      })
    });

    const data = await res.json();
    removeThinking();

    if (!res.ok) {
      appendMessage("bot", `⚠️ Error: ${data.error || "Something went wrong."}`);
      setStatus("error", "Error");
    } else {
      appendMessage("bot", data.reply);
      setStatus("connected", `Connected · ${data.history_length / 2} turns`);
    }

  } catch (err) {
    removeThinking();
    appendMessage("bot", "⚠️ Could not reach the server. Is server.py running?");
    setStatus("error", "Offline");
  }

  sendBtn.disabled = false;
}

// ── Clear conversation ────────────────────────────────────────
async function clearChat() {
  try {
    await fetch(`${API_URL}/clear`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SESSION_ID })
    });
  } catch (_) {}

  messagesEl.innerHTML = `
    <div class="welcome">
      <div class="welcome-icon">⬡</div>
      // ✅ New
      <h2>Hello! I'm your Groq Agent</h2>
      <p>Enter your Groq API key in the sidebar, then start chatting.</p>
    </div>`;
  setStatus("", "Disconnected");
}

// ── Health check on load ──────────────────────────────────────
(async () => {
  try {
    const r = await fetch(`${API_URL}/health`);
    if (r.ok) setStatus("connected", "Server ready");
  } catch {
    setStatus("error", "Server offline");
  }
})();