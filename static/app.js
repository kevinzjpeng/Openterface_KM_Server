(() => {
  /* ------------------------------------------------------------------ */
  /* Terminal                                                             */
  /* ------------------------------------------------------------------ */
  let fontSize = 14;

  const term = new Terminal({
    cursorBlink: true,
    fontSize,
    fontFamily: "'Cascadia Code','Fira Code','Consolas',monospace",
    scrollback: 5000,
    theme: {
      background:   '#0d0f14',
      foreground:   '#c9d1e0',
      cursor:       '#e94560',
      cursorAccent: '#0d0f14',
      selection:    '#2d3550',
      black:        '#1c2030',
      red:          '#e94560',
      green:        '#3ddc84',
      yellow:       '#ffb74d',
      blue:         '#5c9eff',
      magenta:      '#c084fc',
      cyan:         '#22d3ee',
      white:        '#c9d1e0',
      brightBlack:  '#3d4560',
      brightRed:    '#ff6b81',
      brightGreen:  '#6ee7b7',
      brightYellow: '#fde68a',
      brightBlue:   '#93c5fd',
      brightMagenta:'#d8b4fe',
      brightCyan:   '#67e8f9',
      brightWhite:  '#f1f5f9',
    },
  });

  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById('terminal'));
  fitAddon.fit();
  window.addEventListener('resize', () => fitAddon.fit());

  function setFontSize(n) {
    fontSize = Math.min(24, Math.max(8, n));
    term.options.fontSize = fontSize;
    document.getElementById('font-size-display').textContent = fontSize;
    fitAddon.fit();
  }

  /* ------------------------------------------------------------------ */
  /* Stats                                                                */
  /* ------------------------------------------------------------------ */
  let sentCount  = 0;
  let connectedAt = null;
  let prevAgentCount = -1;   // -1 = unknown (fresh load)

  setInterval(() => {
    if (!connectedAt) return;
    const s = Math.floor((Date.now() - connectedAt) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    document.getElementById('sb-uptime').textContent = mm + ':' + ss;
  }, 1000);

  function incSent() {
    sentCount++;
    document.getElementById('sb-sent').textContent = sentCount;
  }

  /* ------------------------------------------------------------------ */
  /* WebSocket                                                            */
  /* ------------------------------------------------------------------ */
  const wsUrl = (location.protocol === 'https:' ? 'wss' : 'ws')
                + '://' + location.host + '/ws';
  let ws;
  let reconnectTimer;

  const serverPill  = document.getElementById('server-pill');
  const serverLabel = document.getElementById('server-label');
  const agentPill   = document.getElementById('agent-pill');
  const agentLabel  = document.getElementById('agent-label');
  const sbReconnect = document.getElementById('sb-reconnect');

  function setServerStatus(state) {   // 'ok' | 'bad' | 'wait'
    serverPill.className = 'pill ' + state;
    sbReconnect.style.display = (state === 'bad') ? '' : 'none';
    if (state === 'ok')   serverLabel.textContent = 'Connected';
    if (state === 'bad')  serverLabel.textContent = 'Disconnected';
    if (state === 'wait') serverLabel.textContent = 'Connecting\u2026';
  }

  function setAgentStatus(count) {
    const active = count > 0;
    agentPill.className = 'pill' + (active ? ' active' : '');
    agentLabel.textContent = active ? 'Agent \u00d7' + count : 'No agent';

    // only print banner on actual transitions, not on the initial status push
    if (prevAgentCount !== -1) {
      if (count > 0 && prevAgentCount === 0) {
        banner('\r\n\x1b[1;32m  \u2714 Agent connected \u2013 keyboard control is live.\x1b[0m\r');
      } else if (count === 0 && prevAgentCount > 0) {
        banner('\r\n\x1b[1;33m  \u26a0 Agent disconnected.\x1b[0m\r');
      }
    }
    prevAgentCount = count;
  }

  function banner(line) { term.writeln(line); }

  function connect() {
    setServerStatus('wait');
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      connectedAt = Date.now();
      prevAgentCount = -1;   // reset so next agent_status is treated as initial
      setServerStatus('ok');
      banner('\r\n\x1b[1;32m \u250f\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2513\x1b[0m');
      banner('\x1b[1;32m \u2503  KeyMod \u2013 Remote KM Control   \u2503\x1b[0m');
      banner('\x1b[1;32m \u2517\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u251b\x1b[0m');
      banner('\x1b[90m  Server connected. Type to send keystrokes to the target PC.\x1b[0m');
      banner('\x1b[90m  Press \x1b[37mF1\x1b[90m for help, \x1b[37mCtrl+L\x1b[90m to clear.\x1b[0m\r');
      // Fetch session timing (fallback for reconnects / direct page-load)
      fetchSessionInfo();
    };

    ws.onmessage = (evt) => {
      if (typeof evt.data !== 'string') return;
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'ping') {
          // reply to keepalive so the server knows we're still here
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'pong'}));
          return;
        }
        if (msg.type === 'agent_status') {
          setAgentStatus(msg.count);
        } else if (msg.type === 'session_info') {
          initCountdown(msg.expires_at, msg.duration_minutes);
        } else if (msg.type === 'window_title') {
          const wb = document.getElementById('sb-window');
          const wt = document.getElementById('sb-window-title');
          if (msg.title) {
            wt.textContent = msg.title;
            wb.style.display = '';
          } else {
            wb.style.display = 'none';
          }
        } else if (msg.type === 'ack') {
          if (_pendingAck.has(msg.id)) { _pendingAck.delete(msg.id); showAck(); }
        } else if (msg.type === 'echo') {
          term.write(msg.data);
        } else if (msg.type === 'terminal_output') {
          // Terminal mode: agent sends output back
          term.write(msg.data);
          incSent();
        } else if (msg.type === 'screenshot') {
          const overlay = document.getElementById('screenshot-overlay');
          const img     = document.getElementById('screenshot-img');
          const spinner = document.getElementById('screenshot-spinner');
          const errDiv  = document.getElementById('screenshot-err');
          const meta    = document.getElementById('screenshot-meta');
          spinner.style.display = 'none';
          errDiv.style.display  = 'none';
          img.src = msg.data;
          img.style.display = 'block';
          meta.textContent = msg.width + '\u00d7' + msg.height;
          overlay.classList.add('show');
        } else if (msg.type === 'screenshot_error') {
          const overlay = document.getElementById('screenshot-overlay');
          const spinner = document.getElementById('screenshot-spinner');
          const errDiv  = document.getElementById('screenshot-err');
          spinner.style.display = 'none';
          errDiv.textContent    = '\u26a0 ' + (msg.error || 'Screenshot failed');
          errDiv.style.display  = 'block';
          overlay.classList.add('show');
        }
      } catch (_) {}
    };

    ws.onclose = () => {
      setServerStatus('bad');
      connectedAt = null;
      document.getElementById('sb-uptime').textContent = '\u2013\u2013:00';
      setAgentStatus(0);
      banner('\r\n\x1b[1;31m  \u2716 Connection lost. Reconnecting in 5 s\u2026\x1b[0m\r');
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 5000);
    };

    ws.onerror = () => ws.close();
  }

  connect();

  /* ------------------------------------------------------------------ */
  /* Key input                                                            */
  /* ------------------------------------------------------------------ */
  // _sendLock prevents a feedback loop when the agent runs on the same
  // machine as the browser: pynput injects keystrokes back into the
  // focused browser window, which would re-trigger onData indefinitely.
  let _sendLock = false;
  let _sendLockTimer = null;

  term.onData((data) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (_sendLock) return;          // drop echoed-back keystroke
    ws.send(JSON.stringify({ type: 'key', data }));
    incSent();
    // Hold the lock for 200 ms – enough time for the injected keystroke
    // to reach and be consumed, but short enough not to feel laggy.
    _sendLock = true;
    clearTimeout(_sendLockTimer);
    _sendLockTimer = setTimeout(() => { _sendLock = false; }, 200);
  });

  /* ------------------------------------------------------------------ */
  /* Toolbar buttons                                                      */
  /* ------------------------------------------------------------------ */
  document.getElementById('btn-font-dec').onclick = () => setFontSize(fontSize - 1);
  document.getElementById('btn-font-inc').onclick = () => setFontSize(fontSize + 1);

  document.getElementById('btn-clear').onclick = () => {
    term.clear();
    term.focus();
  };

  const helpOverlay = document.getElementById('help-overlay');
  // Screenshot
  const screenshotOverlay = document.getElementById('screenshot-overlay');
  function openScreenshot() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const spinner = document.getElementById('screenshot-spinner');
    const img     = document.getElementById('screenshot-img');
    const errDiv  = document.getElementById('screenshot-err');
    spinner.style.display = 'block';
    img.style.display     = 'none';
    errDiv.style.display  = 'none';
    document.getElementById('screenshot-meta').textContent = '';
    screenshotOverlay.classList.add('show');
    ws.send(JSON.stringify({ type: 'screenshot_request' }));
    incSent();
  }
  document.getElementById('btn-screenshot').onclick = openScreenshot;
  document.getElementById('btn-screenshot-refresh').onclick = openScreenshot;
  document.getElementById('btn-screenshot-close').onclick = () => { screenshotOverlay.classList.remove('show'); term.focus(); };
  screenshotOverlay.addEventListener('click', (e) => { if (e.target === screenshotOverlay) { screenshotOverlay.classList.remove('show'); term.focus(); } });

  document.getElementById('btn-help').onclick      = () => { helpOverlay.classList.add('show'); };
  document.getElementById('btn-help-close').onclick = () => { helpOverlay.classList.remove('show'); term.focus(); };
  helpOverlay.addEventListener('click', (e) => { if (e.target === helpOverlay) { helpOverlay.classList.remove('show'); term.focus(); } });

  /* ------------------------------------------------------------------ */
  /* Global keyboard shortcuts                                            */
  /* ------------------------------------------------------------------ */
  window.addEventListener('keydown', (e) => {
    if (e.key === 'F1')  { e.preventDefault(); helpOverlay.classList.toggle('show'); }
    if (e.ctrlKey && e.key === 'l') { e.preventDefault(); term.clear(); }
    if (e.ctrlKey && (e.key === '=' || e.key === '+')) { e.preventDefault(); setFontSize(fontSize + 1); }
    if (e.ctrlKey && e.key === '-') { e.preventDefault(); setFontSize(fontSize - 1); }
  });

  /* ------------------------------------------------------------------ */
  /* Quick Keys                                                           */
  /* ------------------------------------------------------------------ */
  const QUICK_KEYS = {
    nav: [
      { label: '↑',    data: '\x1b[A' },
      { label: '↓',    data: '\x1b[B' },
      { label: '←',    data: '\x1b[D' },
      { label: '→',    data: '\x1b[C' },
      { label: 'Home', data: '\x1b[H' },
      { label: 'End',  data: '\x1b[F' },
      { label: 'PgUp', data: '\x1b[5~' },
      { label: 'PgDn', data: '\x1b[6~' },
      { label: 'Esc',  data: '\x1b'   },
      { label: 'Tab',  data: '\t'     },
      { label: '↵',    data: '\r',    title: 'Enter' },
      { label: '⌫',    data: '\x7f',  title: 'Backspace' },
    ],
    edit: [
      { label: 'Ctrl+C', data: '\x03' },
      { label: 'Ctrl+V', data: '\x16' },
      { label: 'Ctrl+X', data: '\x18' },
      { label: 'Ctrl+Z', data: '\x1a' },
      { label: 'Ctrl+A', data: '\x01' },
      { label: 'Ctrl+S', data: '\x13' },
      { label: 'Del',    data: '\x1b[3~' },
      { label: 'Ins',    data: '\x1b[2~' },
    ],
  };

  /* ------------------------------------------------------------------ */
  /* OS-specific System shortcuts                                        */
  /* ------------------------------------------------------------------ */
  const SYS_KEYS_BY_OS = {
    windows: [
      { label: 'Win',     hotkey: 'win',          title: 'Windows key' },
      { label: 'Win+D',   hotkey: 'win+d',        title: 'Show Desktop' },
      { label: 'Win+R',   hotkey: 'win+r',        title: 'Run dialog' },
      { label: 'Win+L',   hotkey: 'win+l',        title: 'Lock screen' },
      { label: 'Win+E',   hotkey: 'win+e',        title: 'File Explorer' },
      { label: 'Win+Tab', hotkey: 'win+tab',      title: 'Task View' },
      { label: 'C+A+D',   hotkey: 'ctrl+alt+del', title: 'Ctrl+Alt+Del' },
      { label: 'Alt+F4',  hotkey: 'alt+f4',       title: 'Close window' },
    ],
    macos: [
      { label: '\u2318Space',  hotkey: 'cmd+space',   title: 'Spotlight' },
      { label: '\u2318Tab',    hotkey: 'cmd+tab',     title: 'App Switcher' },
      { label: '\u2318Q',      hotkey: 'cmd+q',       title: 'Quit app' },
      { label: '\u2318H',      hotkey: 'cmd+h',       title: 'Hide window' },
      { label: '\u2318M',      hotkey: 'cmd+m',       title: 'Minimize' },
      { label: '\u2318W',      hotkey: 'cmd+w',       title: 'Close window' },
      { label: '\u2303\u2318Q', hotkey: 'ctrl+cmd+q', title: 'Lock screen' },
      { label: '\u2318\u2325Esc', hotkey: 'cmd+opt+esc', title: 'Force Quit' },
    ],
    linux: [
      { label: 'Super',   hotkey: 'super',        title: 'Activities / launcher' },
      { label: 'Super+D', hotkey: 'super+d',      title: 'Show Desktop' },
      { label: 'C+A+T',   hotkey: 'ctrl+alt+t',   title: 'Open Terminal' },
      { label: 'C+A+L',   hotkey: 'ctrl+alt+l',   title: 'Lock screen' },
      { label: 'C+A+D',   hotkey: 'ctrl+alt+del', title: 'Log out' },
      { label: 'Alt+F4',  hotkey: 'alt+f4',       title: 'Close window' },
      { label: 'Alt+Tab', hotkey: 'alt+tab',      title: 'Switch windows' },
      { label: 'PrtSc',   hotkey: 'prtsc',        title: 'Screenshot' },
    ],
  };

  let targetOS = localStorage.getItem('km_target_os') || 'macos';

  /* ------------------------------------------------------------------ */
  /* Session countdown                                                    */
  /* ------------------------------------------------------------------ */
  let _countdownTimer = null;
  let _warnedAt5 = false;
  let _warnedAt1 = false;

  function initCountdown(expiresAt, durationMinutes) {
    const expiry = new Date(expiresAt).getTime();
    if (isNaN(expiry)) return;
    document.getElementById('sb-session-wrap').style.display = '';
    clearInterval(_countdownTimer);
    _warnedAt5 = false;
    _warnedAt1 = false;

    function tick() {
      const remaining = Math.max(0, Math.round((expiry - Date.now()) / 1000));
      const mm = String(Math.floor(remaining / 60)).padStart(2, '0');
      const ss = String(remaining % 60).padStart(2, '0');
      const el = document.getElementById('sb-session');

      if (remaining <= 0) {
        el.textContent = 'Ended';
        el.className = 'ended';
        clearInterval(_countdownTimer);
        banner('\r\n\x1b[1;31m  ⚠  Session has ended – the GitHub Actions runner has stopped.\x1b[0m\r');
        return;
      }

      el.textContent = mm + ':' + ss;

      if (remaining <= 120) {
        el.className = 'urgent';
        if (!_warnedAt1) {
          _warnedAt1 = true;
          banner('\r\n\x1b[1;31m  ⚠  Less than 2 minutes left in this session!\x1b[0m\r');
        }
      } else if (remaining <= 300) {
        el.className = 'warn';
        if (!_warnedAt5) {
          _warnedAt5 = true;
          banner('\r\n\x1b[1;33m  ⚠  5 minutes remaining in this session.\x1b[0m\r');
        }
      } else {
        el.className = 'ok';
      }
    }

    tick();
    _countdownTimer = setInterval(tick, 1000);
  }

  /* Fallback: fetch /session-info once after connecting (catches page-reload case) */
  function fetchSessionInfo() {
    fetch('/session-info').then(r => r.json()).then(d => {
      if (d.expires_at) initCountdown(d.expires_at, d.duration_minutes);
    }).catch(() => {});
  }

  /* ------------------------------------------------------------------ */
  /* Panel collapse / expand (VS Code-style)                             */
  /* ------------------------------------------------------------------ */
  const _PANEL_DEFAULTS = {
    'sec-qkeys': true,
    'sec-send':  true,
    'sec-hist':  true,
    'sec-macros':true,
  };

  function initPanels() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('km_panels') || '{}'); } catch(e) {}
    const state = Object.assign({}, _PANEL_DEFAULTS, saved);
    Object.keys(_PANEL_DEFAULTS).forEach(id => {
      const sec = document.getElementById(id);
      if (!sec) return;
      if (!state[id]) sec.classList.add('collapsed');
    });
  }

  // Exposed globally so inline onclick="toggleSection(...)" handlers can reach it
  window.toggleSection = function toggleSection(id) {
    const sec = document.getElementById(id);
    if (!sec) return;
    sec.classList.toggle('collapsed');
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('km_panels') || '{}'); } catch(e) {}
    saved[id] = !sec.classList.contains('collapsed');
    localStorage.setItem('km_panels', JSON.stringify(saved));
  };

  let _msgId = 0;
  const _pendingAck = new Map();
  let _ackHideTimer = null;

  function nextMsgId() { return 'k' + (++_msgId); }

  function showAck() {
    const el = document.getElementById('sb-ack');
    el.style.display = '';
    el.classList.remove('flash');
    void el.offsetWidth;
    el.classList.add('flash');
    clearTimeout(_ackHideTimer);
    _ackHideTimer = setTimeout(() => { el.style.display = 'none'; }, 2200);
  }

  function sendRaw(data) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const id = nextMsgId();
    ws.send(JSON.stringify({ type: 'key', data, id }));
    _pendingAck.set(id, true);
    incSent();
  }

  function sendHotkey(combo) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const id = nextMsgId();
    ws.send(JSON.stringify({ type: 'hotkey', combo, id }));
    _pendingAck.set(id, true);
    incSent();
  }

  function buildQuickGrid(tabId, keys) {
    const grid = document.getElementById('qtab-' + tabId);
    keys.forEach(k => {
      const btn = document.createElement('button');
      btn.className = 'qkey';
      btn.textContent = k.label;
      if (k.title) btn.title = k.title;
      btn.addEventListener('click', () => {
        if (k.hotkey) sendHotkey(k.hotkey);
        else          sendRaw(k.data);
        term.focus();
      });
      grid.appendChild(btn);
    });
  }

  function renderSysTab() {
    const osSel = document.getElementById('os-selector');
    const grid  = document.getElementById('qtab-sys-grid');

    // Rebuild OS selector pills
    osSel.innerHTML = '';
    [['windows', '\uD83E\uDEDF Windows'], ['macos', '\uD83C\uDF4E macOS'], ['linux', '\uD83D\uDC27 Linux']].forEach(([id, lbl]) => {
      const btn = document.createElement('button');
      btn.className = 'os-pill' + (targetOS === id ? ' active' : '');
      btn.textContent = lbl;
      btn.addEventListener('click', () => {
        targetOS = id;
        localStorage.setItem('km_target_os', targetOS);
        renderSysTab();
        term.focus();
      });
      osSel.appendChild(btn);
    });

    // Rebuild key grid
    grid.innerHTML = '';
    (SYS_KEYS_BY_OS[targetOS] || []).forEach(k => {
      const btn = document.createElement('button');
      btn.className = 'qkey';
      btn.textContent = k.label;
      if (k.title) btn.title = k.title;
      btn.addEventListener('click', () => {
        if (k.hotkey) sendHotkey(k.hotkey);
        else          sendRaw(k.data);
        term.focus();
      });
      grid.appendChild(btn);
    });
  }

  ['nav', 'edit'].forEach(id => buildQuickGrid(id, QUICK_KEYS[id]));
  renderSysTab();

  document.querySelectorAll('.qtab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.qtab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.quick-grid, .sys-panel').forEach(g => g.classList.add('hidden'));
      tab.classList.add('active');
      document.getElementById('qtab-' + tab.dataset.tab).classList.remove('hidden');
    });
  });

  /* ------------------------------------------------------------------ */
  /* Send history                                                         */
  /* ------------------------------------------------------------------ */
  const MAX_HISTORY = 20;
  let sendHistory = [];
  try { sendHistory = JSON.parse(localStorage.getItem('km_history') || '[]'); } catch (_) {}

  function fmtTime(ts) {
    const d = new Date(ts);
    return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0');
  }

  function renderHistory() {
    const list = document.getElementById('hist-list');
    const cnt  = document.getElementById('hist-count');
    list.innerHTML = '';
    cnt.textContent = sendHistory.length ? sendHistory.length : '';
    if (!sendHistory.length) {
      list.innerHTML = '<div id="hist-empty">No history yet</div>';
      return;
    }
    // newest first
    [...sendHistory].reverse().forEach((entry, i) => {
      const row = document.createElement('div');
      row.className = 'hist-item';
      row.innerHTML =
        `<span class="hist-ts">${fmtTime(entry.ts)}</span>` +
        `<span class="hist-text" title="${entry.text.replace(/"/g,'&quot;')}">${entry.text}</span>` +
        `<button class="hist-resend" title="Re-send">↑</button>`;
      row.querySelector('.hist-resend').addEventListener('click', () => {
        const data = entry.text.replace(/\r?\n/g, '\r');
        sendRaw(data);
        banner('\x1b[90m  ↑ Re-sent: ' + entry.text.slice(0,40).replace(/\r/g,'↵') + '\x1b[0m');
      });
      list.appendChild(row);
    });
  }

  function pushHistory(text) {
    // Deduplicate: move to top if already exists
    sendHistory = sendHistory.filter(e => e.text !== text);
    sendHistory.push({ ts: Date.now(), text });
    if (sendHistory.length > MAX_HISTORY) sendHistory.shift();
    try { localStorage.setItem('km_history', JSON.stringify(sendHistory)); } catch (_) {}
    renderHistory();
  }

  renderHistory();

  /* ------------------------------------------------------------------ */
  /* Input templates                                                      */
  /* ------------------------------------------------------------------ */
  const TEMPLATES = [
    { label: 'IP addr',        text: '192.168.1.' },
    { label: 'sudo …',          text: 'sudo ' },
    { label: 'apt install',    text: 'sudo apt-get install -y ' },
    { label: 'SSH connect',    text: 'ssh user@host' },
    { label: 'python3 run',    text: 'python3 script.py' },
    { label: 'docker ps',      text: 'docker ps -a' },
    { label: 'Win+R: cmd',     text: 'cmd' },
    { label: 'Win+R: notepad', text: 'notepad' },
  ];

  const tplSelect = document.getElementById('tpl-select');
  TEMPLATES.forEach(t => {
    const o = document.createElement('option');
    o.value = t.text; o.textContent = t.label;
    tplSelect.appendChild(o);
  });
  tplSelect.addEventListener('change', () => {
    if (!tplSelect.value) return;
    const target = maskOn ? maskedInput : textInput;
    target.value = tplSelect.value;
    target.focus();
    target.setSelectionRange(target.value.length, target.value.length);
    tplSelect.value = '';
  });

  /* ------------------------------------------------------------------ */
  /* Mask mode                                                            */
  /* ------------------------------------------------------------------ */
  const maskedInput = document.getElementById('masked-input');
  const btnMask     = document.getElementById('btn-mask');
  let maskOn = false;

  btnMask.addEventListener('click', () => {
    maskOn = !maskOn;
    btnMask.classList.toggle('on', maskOn);
    btnMask.title = maskOn ? 'Disable password mask' : 'Enable password mask';
    if (maskOn) {
      maskedInput.value = textInput.value;
      textInput.style.display = 'none';
      maskedInput.style.display = '';
      maskedInput.focus();
    } else {
      textInput.value = maskedInput.value;
      maskedInput.style.display = 'none';
      textInput.style.display = '';
      textInput.focus();
    }
  });

  maskedInput.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); sendText(); }
    e.stopPropagation();
  });

  /* ------------------------------------------------------------------ */
  /* Macros                                                               */
  /* ------------------------------------------------------------------ */
  const DEFAULT_MACROS = [
    { id:'dm1', name:'Show Desktop',  steps:[{t:'hotkey',v:'win+d'}] },
    { id:'dm2', name:'Open Run…',    steps:[{t:'hotkey',v:'win+r'}] },
    { id:'dm3', name:'Open Notepad',  steps:[{t:'hotkey',v:'win+r'},{t:'wait',v:'500'},{t:'key',v:'notepad\r'}] },
    { id:'dm4', name:'Open Terminal', steps:[{t:'hotkey',v:'win+r'},{t:'wait',v:'500'},{t:'key',v:'cmd\r'}] },
    { id:'dm5', name:'Lock Screen',   steps:[{t:'hotkey',v:'win+l'}] },
  ];

  let macros = [];
  try { macros = JSON.parse(localStorage.getItem('km_macros') || 'null') || DEFAULT_MACROS.map(m=>({...m,steps:m.steps.map(s=>({...s}))}) ); }
  catch (_) { macros = DEFAULT_MACROS.map(m=>({...m,steps:m.steps.map(s=>({...s}))})); }

  function saveMacroData() {
    try { localStorage.setItem('km_macros', JSON.stringify(macros)); } catch (_) {}
  }

  function escForEdit(s)   { return s.replace(/\r/g,'\\r').replace(/\t/g,'\\t'); }
  function unescFromEdit(s){ return s.replace(/\\r/g,'\r').replace(/\\t/g,'\t').replace(/\\n/g,'\r'); }

  function renderMacroList() {
    const list = document.getElementById('macro-list');
    list.innerHTML = '';
    if (!macros.length) {
      list.innerHTML = '<div class="macro-empty">No macros yet</div>';
      return;
    }
    macros.forEach(m => {
      const row = document.createElement('div');
      row.className = 'macro-row';
      row.innerHTML =
        `<button class="macro-run" title="Run: ${m.name}">${m.name}</button>` +
        `<button class="macro-icon-btn" title="Edit">✎</button>` +
        `<button class="macro-icon-btn" title="Delete" style="color:var(--accent)">×</button>`;
      row.querySelector('.macro-run').addEventListener('click', () => runMacroById(m.id));
      row.querySelectorAll('.macro-icon-btn')[0].addEventListener('click', () => openMacroEditor(m));
      row.querySelectorAll('.macro-icon-btn')[1].addEventListener('click', () => {
        if (!confirm(`Delete macro "${m.name}"?`)) return;
        macros = macros.filter(x => x.id !== m.id);
        saveMacroData(); renderMacroList();
      });
      list.appendChild(row);
    });
  }

  async function runMacroById(id) {
    const m = macros.find(x => x.id === id);
    if (!m) return;
    banner(`\x1b[90m  ▶ ${m.name}\x1b[0m`);
    for (const step of m.steps) {
      if      (step.t === 'key')    sendRaw(step.v);
      else if (step.t === 'hotkey') sendHotkey(step.v);
      else if (step.t === 'wait')   await new Promise(r => setTimeout(r, Math.max(0, Number(step.v) || 500)));
    }
    banner(`\x1b[90m  \u2714 Done: ${m.name}\x1b[0m`);
  }

  // ----- Macro editor -----
  const macroOverlay = document.getElementById('macro-overlay');
  let macroEditId = null;

  function openMacroEditor(macro) {
    macroEditId = macro ? macro.id : null;
    document.getElementById('macro-modal-title').textContent = macro ? 'Edit Macro' : 'New Macro';
    document.getElementById('macro-name').value = macro ? macro.name : '';
    const stepsEl = document.getElementById('msteps-list');
    stepsEl.innerHTML = '';
    if (macro) {
      macro.steps.forEach(s => addMstepRow(s.t, s.t === 'key' ? escForEdit(s.v) : s.v));
    } else {
      addMstepRow('hotkey', 'win+r');
      addMstepRow('wait', '400');
      addMstepRow('key', '');
    }
    macroOverlay.classList.add('show');
    document.getElementById('macro-name').focus();
  }

  function closeMacroEditor() { macroOverlay.classList.remove('show'); macroEditId = null; }

  function addMstepRow(type, value) {
    const stepsEl = document.getElementById('msteps-list');
    const row = document.createElement('div'); row.className = 'mstep';
    const sel = document.createElement('select'); sel.className = 'mstep-type';
    [{v:'key',l:'Key text'},{v:'hotkey',l:'Hotkey'},{v:'wait',l:'Wait ms'}].forEach(o => {
      const opt = document.createElement('option'); opt.value = o.v; opt.textContent = o.l;
      if (o.v === type) opt.selected = true;
      sel.appendChild(opt);
    });
    const inp = document.createElement('input'); inp.className = 'mstep-val'; inp.type = 'text';
    const placeholders = { key:'hello world\\r', hotkey:'win+r', wait:'500' };
    inp.placeholder = placeholders[type] || '';
    inp.value = value || '';
    sel.addEventListener('change', () => { inp.placeholder = placeholders[sel.value] || ''; });
    const del = document.createElement('button'); del.className = 'mstep-del'; del.textContent = '×';
    del.addEventListener('click', () => row.remove());
    row.append(sel, inp, del);
    stepsEl.appendChild(row);
  }

  document.getElementById('btn-macro-new').addEventListener('click', () => openMacroEditor(null));
  document.getElementById('btn-macro-close').addEventListener('click', closeMacroEditor);
  document.getElementById('btn-macro-cancel').addEventListener('click', closeMacroEditor);
  macroOverlay.addEventListener('click', e => { if (e.target === macroOverlay) closeMacroEditor(); });
  document.getElementById('mstep-add-key').addEventListener('click', () => addMstepRow('key', ''));
  document.getElementById('mstep-add-hotkey').addEventListener('click', () => addMstepRow('hotkey', ''));
  document.getElementById('mstep-add-wait').addEventListener('click', () => addMstepRow('wait', '500'));

  document.getElementById('btn-macro-save').addEventListener('click', () => {
    const name = document.getElementById('macro-name').value.trim();
    if (!name) { alert('Please enter a macro name.'); return; }
    const stepRows = document.querySelectorAll('#msteps-list .mstep');
    const steps = [];
    stepRows.forEach(row => {
      const t = row.querySelector('.mstep-type').value;
      const v = row.querySelector('.mstep-val').value;
      if (!v) return;
      steps.push({ t, v: t === 'key' ? unescFromEdit(v) : v });
    });
    if (!steps.length) { alert('Add at least one step with a value.'); return; }
    if (macroEditId) {
      const idx = macros.findIndex(m => m.id === macroEditId);
      if (idx >= 0) macros[idx] = { id: macroEditId, name, steps };
    } else {
      macros.push({ id: 'u' + Date.now(), name, steps });
    }
    saveMacroData(); renderMacroList(); closeMacroEditor();
  });

  initPanels();
  renderMacroList();

  /* ------------------------------------------------------------------ */
  /* Send-text panel                                                      */
  /* ------------------------------------------------------------------ */
  const textInput   = document.getElementById('text-input');
  const btnSendText = document.getElementById('btn-send-text');

  function sendText() {
    const activeInput = maskOn ? maskedInput : textInput;
    const raw = activeInput.value.trim();
    if (!raw || !ws || ws.readyState !== WebSocket.OPEN) return;
    const data = raw.replace(/\r?\n/g, '\r');
    activeInput.value = '';   // clear immediately so UI feels responsive
    activeInput.focus();
    sendRaw(data);
    if (!maskOn) pushHistory(raw);  // never save passwords to history
  }

  btnSendText.addEventListener('click', sendText);

  textInput.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); sendText(); }
  });

  // Prevent global shortcuts while textarea is focused
  textInput.addEventListener('keydown', (e) => e.stopPropagation());

  /* auto-focus terminal on load */
  term.focus();
})();
