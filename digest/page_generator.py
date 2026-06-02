import os
import re
from datetime import datetime


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _escape_for_js_template(text: str) -> str:
    """Escape text for safe embedding in a JS template literal."""
    text = text.replace("\\", "\\\\")
    text = text.replace("`", "\\`")
    text = text.replace("${", "\\${")
    return text


_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Launch Digest — DATE_PLACEHOLDER</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    html, body {
      height: 100%;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: #f0f2f5;
      color: #1a1a2e;
    }

    /* Layout */
    #app {
      display: flex;
      height: 100vh;
      overflow: hidden;
    }

    /* Digest panel */
    #digest-panel {
      flex: 1 1 60%;
      min-width: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    #digest-header {
      background: #1a1a2e;
      color: white;
      padding: 18px 32px;
      flex-shrink: 0;
    }

    #digest-header h1 {
      font-size: 19px;
      font-weight: 700;
      letter-spacing: -0.3px;
    }

    #digest-header .date {
      font-size: 12px;
      color: #8888aa;
      margin-top: 3px;
    }

    #digest-scroll {
      flex: 1;
      overflow-y: auto;
      padding: 24px 32px;
      background: #f0f2f5;
    }

    .digest-section {
      background: white;
      border-radius: 8px;
      padding: 24px 28px;
      margin-bottom: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.07);
    }

    .section-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1.2px;
      text-transform: uppercase;
      margin-bottom: 18px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .section-label::before {
      content: "";
      display: inline-block;
      width: 3px;
      height: 14px;
      border-radius: 2px;
    }

    .section-label.funding { color: #0055cc; }
    .section-label.funding::before { background: #0055cc; }
    .section-label.launches { color: #007744; }
    .section-label.launches::before { background: #007744; }

    /* Chat panel */
    #chat-panel {
      flex: 0 0 380px;
      display: flex;
      flex-direction: column;
      background: #1a1a2e;
      color: #e0e0f0;
      border-left: 1px solid rgba(255,255,255,0.06);
    }

    #chat-header {
      padding: 16px 18px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }

    #chat-header h2 {
      font-size: 14px;
      font-weight: 600;
      color: #fff;
    }

    #chat-header .subtitle {
      font-size: 11px;
      color: #6666aa;
      margin-top: 2px;
    }

    #change-key-btn {
      background: none;
      border: 1px solid rgba(255,255,255,0.12);
      color: #8888bb;
      font-size: 11px;
      padding: 4px 8px;
      border-radius: 4px;
      cursor: pointer;
    }

    #change-key-btn:hover { border-color: rgba(255,255,255,0.28); color: #aaaacc; }

    #messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    #messages:empty::before {
      content: "Dig deeper on any company, launch, or theme — ask why a rating landed where it did, how a launch compares to past examples, or what you should watch next.";
      color: #44446a;
      font-size: 13px;
      line-height: 1.65;
      display: block;
      padding: 4px 0;
    }

    .message {
      max-width: 92%;
      padding: 10px 13px;
      border-radius: 12px;
      font-size: 13px;
      line-height: 1.65;
      word-wrap: break-word;
      white-space: pre-wrap;
    }

    .message.user {
      background: #0055cc;
      color: white;
      align-self: flex-end;
      border-bottom-right-radius: 3px;
    }

    .message.assistant {
      background: #272740;
      color: #d0d0e8;
      align-self: flex-start;
      border-bottom-left-radius: 3px;
    }

    .message.error {
      background: #3a1a1a;
      color: #ff8888;
      align-self: flex-start;
    }

    @keyframes pulse {
      0%, 100% { opacity: 0.25; }
      50% { opacity: 1; }
    }

    .message.loading .message-content::after {
      content: "●●●";
      letter-spacing: 3px;
      font-size: 9px;
      animation: pulse 1.3s infinite;
    }

    #chat-input-area {
      padding: 12px;
      border-top: 1px solid rgba(255,255,255,0.07);
      display: flex;
      gap: 8px;
      align-items: flex-end;
      flex-shrink: 0;
    }

    #chat-input {
      flex: 1;
      background: #272740;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 8px;
      color: #e0e0f0;
      font-family: inherit;
      font-size: 13px;
      padding: 9px 12px;
      resize: none;
      min-height: 40px;
      max-height: 120px;
      line-height: 1.5;
      outline: none;
      overflow-y: auto;
    }

    #chat-input:focus { border-color: rgba(0, 85, 204, 0.6); }
    #chat-input::placeholder { color: #44446a; }

    #send-btn {
      background: #0055cc;
      color: white;
      border: none;
      border-radius: 8px;
      width: 36px;
      height: 36px;
      cursor: pointer;
      font-size: 15px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: background 0.15s;
    }

    #send-btn:hover { background: #0044aa; }
    #send-btn:disabled { background: #2a2a44; cursor: not-allowed; }

    /* API key modal */
    #modal-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.72);
      align-items: center;
      justify-content: center;
      z-index: 100;
      backdrop-filter: blur(4px);
    }

    #modal-overlay.visible { display: flex; }

    #modal {
      background: #1e1e30;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 12px;
      padding: 28px 32px;
      width: 400px;
      max-width: 90vw;
    }

    #modal h2 { font-size: 17px; color: #fff; margin-bottom: 8px; }

    #modal .modal-desc {
      font-size: 13px;
      color: #8888aa;
      line-height: 1.65;
      margin-bottom: 18px;
    }

    #modal-key-input {
      width: 100%;
      background: #272740;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 7px;
      color: #e0e0f0;
      font-family: monospace;
      font-size: 13px;
      padding: 10px 12px;
      outline: none;
      margin-bottom: 12px;
    }

    #modal-key-input:focus { border-color: rgba(0, 85, 204, 0.7); }

    #modal-save-btn {
      width: 100%;
      background: #0055cc;
      color: white;
      border: none;
      border-radius: 7px;
      padding: 10px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }

    #modal-save-btn:hover { background: #0044aa; }

    #modal .modal-note {
      margin-top: 12px;
      font-size: 11px;
      color: #55556a;
      line-height: 1.5;
    }
  </style>
</head>
<body>

  <!-- API key modal -->
  <div id="modal-overlay">
    <div id="modal">
      <h2>Connect Claude</h2>
      <p class="modal-desc">Enter your Anthropic API key to ask follow-up questions about this digest. Your key is stored only in your browser and sent directly to Anthropic's API &mdash; never to any other server.</p>
      <input type="password" id="modal-key-input" placeholder="sk-ant-api03-..." autocomplete="off" spellcheck="false">
      <button id="modal-save-btn" onclick="saveApiKey()">Start chatting &rarr;</button>
      <p class="modal-note">Get your key at console.anthropic.com &rarr; API Keys</p>
    </div>
  </div>

  <!-- App -->
  <div id="app">

    <!-- Digest panel -->
    <div id="digest-panel">
      <div id="digest-header">
        <h1>Weekly Launch Digest</h1>
        <div class="date">Week ending DATE_PLACEHOLDER</div>
      </div>
      <div id="digest-scroll">

        <div class="digest-section">
          <div class="section-label funding">VC Funding Announcements</div>
          FUNDING_CONTENT_PLACEHOLDER
        </div>

        <div class="digest-section">
          <div class="section-label launches">Top B2B Product Launches</div>
          LAUNCHES_CONTENT_PLACEHOLDER
        </div>

      </div>
    </div>

    <!-- Chat panel -->
    <div id="chat-panel">
      <div id="chat-header">
        <div>
          <h2>Ask Claude</h2>
          <div class="subtitle">Follow-up on this digest</div>
        </div>
        <button id="change-key-btn" onclick="showModal()">API key</button>
      </div>
      <div id="messages"></div>
      <div id="chat-input-area">
        <textarea id="chat-input" placeholder="Ask a follow-up…" rows="1"></textarea>
        <button id="send-btn" onclick="handleSend()" title="Send (Enter)">&#9658;</button>
      </div>
    </div>

  </div>

  <script>
    const SYSTEM_CONTEXT = `SYSTEM_CONTEXT_PLACEHOLDER`;
    const history = [];
    let busy = false;

    // ── API key ──────────────────────────────────────────────────

    const KEY_STORE = 'wld_anthropic_key';

    function getKey() { return localStorage.getItem(KEY_STORE) || ''; }

    function saveApiKey() {
      const val = document.getElementById('modal-key-input').value.trim();
      if (!val.startsWith('sk-ant-')) {
        document.getElementById('modal-key-input').style.borderColor = '#cc3333';
        return;
      }
      localStorage.setItem(KEY_STORE, val);
      hideModal();
      document.getElementById('chat-input').focus();
    }

    function showModal() {
      document.getElementById('modal-key-input').value = getKey();
      document.getElementById('modal-key-input').style.borderColor = '';
      document.getElementById('modal-overlay').classList.add('visible');
      setTimeout(() => document.getElementById('modal-key-input').focus(), 60);
    }

    function hideModal() {
      document.getElementById('modal-overlay').classList.remove('visible');
    }

    document.getElementById('modal-overlay').addEventListener('click', function(e) {
      if (e.target === this) hideModal();
    });

    document.getElementById('modal-key-input').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') saveApiKey();
    });

    if (!getKey()) showModal();

    // ── Chat UI ──────────────────────────────────────────────────

    function addMessage(role, text) {
      const wrap = document.createElement('div');
      wrap.className = 'message ' + role;
      const content = document.createElement('span');
      content.className = 'message-content';
      content.textContent = text;
      wrap.appendChild(content);
      document.getElementById('messages').appendChild(wrap);
      scrollBottom();
      return wrap;
    }

    function scrollBottom() {
      const el = document.getElementById('messages');
      el.scrollTop = el.scrollHeight;
    }

    const textarea = document.getElementById('chat-input');

    textarea.addEventListener('input', () => {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    });

    textarea.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
    });

    function handleSend() {
      const text = textarea.value.trim();
      if (!text || busy) return;
      textarea.value = '';
      textarea.style.height = 'auto';
      chat(text);
    }

    // ── Streaming API call ───────────────────────────────────────

    async function chat(userText) {
      if (!getKey()) { showModal(); return; }

      busy = true;
      document.getElementById('send-btn').disabled = true;

      history.push({ role: 'user', content: userText });
      addMessage('user', userText);

      const assistantEl = addMessage('assistant', '');
      assistantEl.classList.add('loading');

      try {
        const res = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: {
            'x-api-key': getKey(),
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
            'anthropic-dangerous-direct-browser-access': 'true',
          },
          body: JSON.stringify({
            model: 'claude-sonnet-4-6',
            max_tokens: 1024,
            stream: true,
            system: SYSTEM_CONTEXT,
            messages: history,
          }),
        });

        assistantEl.classList.remove('loading');

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error?.message || 'HTTP ' + res.status);
        }

        let reply = '';
        const reader = res.body.getReader();
        const dec = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          for (const line of dec.decode(value, { stream: true }).split('\\n')) {
            if (!line.startsWith('data: ')) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;
            try {
              const ev = JSON.parse(raw);
              if (ev.type === 'content_block_delta' && ev.delta?.type === 'text_delta') {
                reply += ev.delta.text;
                assistantEl.querySelector('.message-content').textContent = reply;
                scrollBottom();
              }
            } catch {}
          }
        }

        history.push({ role: 'assistant', content: reply });

      } catch (err) {
        assistantEl.classList.remove('loading');
        assistantEl.classList.add('error');
        assistantEl.querySelector('.message-content').textContent = 'Error: ' + err.message;
        history.pop();
      }

      busy = false;
      document.getElementById('send-btn').disabled = false;
      document.getElementById('chat-input').focus();
    }
  </script>

</body>
</html>"""


def write_digest_page(
    funding_html: str,
    launches_html: str,
    output_path: str = "docs/index.html",
) -> None:
    today = datetime.now().strftime("%B %d, %Y")

    plain_funding = _strip_tags(funding_html)
    plain_launches = _strip_tags(launches_html)

    system_context = (
        f"You are a helpful assistant with deep expertise in B2B product marketing, "
        f"venture capital, and the startup ecosystem. The user has just read the "
        f"Weekly Launch Digest for the week ending {today} and wants to dig deeper on "
        f"what they read. Answer follow-up questions thoughtfully. Draw on your broader "
        f"knowledge when relevant, not just the digest content.\n\n"
        f"DIGEST CONTENT:\n\n"
        f"--- VC FUNDING ANNOUNCEMENTS ---\n{plain_funding}\n\n"
        f"--- TOP B2B PRODUCT LAUNCHES ---\n{plain_launches}"
    )

    html = (
        _HTML
        .replace("DATE_PLACEHOLDER", today)
        .replace("FUNDING_CONTENT_PLACEHOLDER", funding_html)
        .replace("LAUNCHES_CONTENT_PLACEHOLDER", launches_html)
        .replace("SYSTEM_CONTEXT_PLACEHOLDER", _escape_for_js_template(system_context))
    )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
