export function createKeyboardModule({
  getWs,
  sendRaw,
  sendHotkey,
  focusPrimaryInput,
  keyLog,
  getTargetOS,
  setTargetOS,
  applyDefaultMacrosForOS,
}) {
  const QUICK_KEYS = {
    nav: [
      { label: '↑', data: '\x1b[A' },
      { label: '↓', data: '\x1b[B' },
      { label: '←', data: '\x1b[D' },
      { label: '→', data: '\x1b[C' },
      { label: 'Home', data: '\x1b[H' },
      { label: 'End', data: '\x1b[F' },
      { label: 'PgUp', data: '\x1b[5~' },
      { label: 'PgDn', data: '\x1b[6~' },
      { label: 'Esc', data: '\x1b' },
      { label: 'Tab', data: '\t' },
      { label: '↵', data: '\r', title: 'Enter' },
      { label: '⌫', data: '\x7f', title: 'Backspace' },
    ],
    edit: [
      { label: 'Ctrl+C', data: '\x03' },
      { label: 'Ctrl+V', data: '\x16' },
      { label: 'Ctrl+X', data: '\x18' },
      { label: 'Ctrl+Z', data: '\x1a' },
      { label: 'Ctrl+A', data: '\x01' },
      { label: 'Ctrl+S', data: '\x13' },
      { label: 'Del', data: '\x1b[3~' },
      { label: 'Ins', data: '\x1b[2~' },
    ],
  };

  const SYS_KEYS_BY_OS = {
    windows: [
      { label: 'Win', hotkey: 'win', title: 'Windows key' },
      { label: 'Win+D', hotkey: 'win+d', title: 'Show Desktop' },
      { label: 'Win+R', hotkey: 'win+r', title: 'Run dialog' },
      { label: 'Win+L', hotkey: 'win+l', title: 'Lock screen' },
      { label: 'Win+E', hotkey: 'win+e', title: 'File Explorer' },
      { label: 'Win+Tab', hotkey: 'win+tab', title: 'Task View' },
      { label: 'C+A+D', hotkey: 'ctrl+alt+del', title: 'Ctrl+Alt+Del' },
      { label: 'Alt+F4', hotkey: 'alt+f4', title: 'Close window' },
    ],
    macos: [
      { label: '⌘Space', hotkey: 'cmd+space', title: 'Spotlight' },
      { label: '⌘Tab', hotkey: 'cmd+tab', title: 'App Switcher' },
      { label: '⌘Q', hotkey: 'cmd+q', title: 'Quit app' },
      { label: '⌘H', hotkey: 'cmd+h', title: 'Hide window' },
      { label: '⌘M', hotkey: 'cmd+m', title: 'Minimize' },
      { label: '⌘W', hotkey: 'cmd+w', title: 'Close window' },
      { label: '⌃⌘Q', hotkey: 'ctrl+cmd+q', title: 'Lock screen' },
      { label: '⌘⌥Esc', hotkey: 'cmd+opt+esc', title: 'Force Quit' },
    ],
    linux: [
      { label: 'Super', hotkey: 'super', title: 'Activities / launcher' },
      { label: 'Super+D', hotkey: 'super+d', title: 'Show Desktop' },
      { label: 'C+A+T', hotkey: 'ctrl+alt+t', title: 'Open Terminal' },
      { label: 'C+A+L', hotkey: 'ctrl+alt+l', title: 'Lock screen' },
      { label: 'C+A+D', hotkey: 'ctrl+alt+del', title: 'Log out' },
      { label: 'Alt+F4', hotkey: 'alt+f4', title: 'Close window' },
      { label: 'Alt+Tab', hotkey: 'alt+tab', title: 'Switch windows' },
      { label: 'PrtSc', hotkey: 'prtsc', title: 'Screenshot' },
    ],
  };

  function flashVkByToken(token) {
    if (!token) return;
    const t = String(token).trim().toLowerCase();
    const vkbd = document.getElementById('vkbd');
    if (!vkbd) return;

    let nodes = [];
    if (t === 'win' || t === 'super' || t === 'cmd' || t === 'meta') {
      nodes = [...vkbd.querySelectorAll('.vkbd-key[data-mod="meta"]')];
    } else if (t === 'ctrl') {
      nodes = [...vkbd.querySelectorAll('.vkbd-key[data-mod="ctrl"]')];
    } else if (t === 'alt' || t === 'opt' || t === 'option') {
      nodes = [...vkbd.querySelectorAll('.vkbd-key[data-mod="alt"]')];
    } else if (t === 'shift') {
      nodes = [...vkbd.querySelectorAll('.vkbd-key[data-mod="shift"]')];
    } else {
      const normalized = (t === 'space') ? ' ' : t;
      const escaped = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(normalized) : normalized;
      nodes = [...vkbd.querySelectorAll(`.vkbd-key[data-key="${escaped}"]`)];
      if (!nodes.length && normalized.length === 1) {
        const lower = normalized.toLowerCase();
        const escapedLower = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(lower) : lower;
        nodes = [...vkbd.querySelectorAll(`.vkbd-key[data-key="${escapedLower}"]`)];
      }
    }

    nodes.forEach((el) => {
      el.classList.add('active');
      setTimeout(() => el.classList.remove('active'), 130);
    });
  }

  function flashVkByCombo(combo) {
    if (!combo) return;
    String(combo).split('+').map(s => s.trim()).filter(Boolean).forEach(flashVkByToken);
  }

  function flashVkByRawData(data) {
    const raw = String(data ?? '');
    const map = {
      '\x1b[A': ['up'],
      '\x1b[B': ['down'],
      '\x1b[C': ['right'],
      '\x1b[D': ['left'],
      '\x1b[H': ['home'],
      '\x1b[F': ['end'],
      '\x1b[5~': ['pgup'],
      '\x1b[6~': ['pgdn'],
      '\x1b[3~': ['delete'],
      '\x1b[2~': ['insert'],
      '\x1b': ['esc'],
      '\t': ['tab'],
      '\r': ['enter'],
      '\x7f': ['backspace'],
    };
    if (map[raw]) {
      map[raw].forEach(flashVkByToken);
      return;
    }
    if (raw.length === 1) flashVkByToken(raw);
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
        else sendRaw(k.data);
        focusPrimaryInput();
      });
      grid.appendChild(btn);
    });
  }

  function renderSysTab() {
    const targetOS = getTargetOS();
    const osSel = document.getElementById('os-selector');
    const grid = document.getElementById('qtab-sys-grid');

    osSel.innerHTML = '';
    [['windows', '🪟 Windows'], ['macos', '🍎 macOS'], ['linux', '🐧 Linux']].forEach(([id, lbl]) => {
      const btn = document.createElement('button');
      btn.className = 'os-pill' + (targetOS === id ? ' active' : '');
      btn.textContent = lbl;
      btn.addEventListener('click', () => {
        setTargetOS(id);
        localStorage.setItem('km_target_os', id);
        applyDefaultMacrosForOS(id);
        renderSysTab();
        updateMetaLabel();
        focusPrimaryInput();
      });
      osSel.appendChild(btn);
    });

    grid.innerHTML = '';
    if (targetOS === 'unknown') {
      const msg = document.createElement('div');
      msg.style.padding = '20px';
      msg.style.textAlign = 'center';
      msg.style.color = '#888';
      msg.textContent = 'Select your OS or connect an agent to auto-detect…';
      grid.appendChild(msg);
      return;
    }

    (SYS_KEYS_BY_OS[targetOS] || []).forEach(k => {
      const btn = document.createElement('button');
      btn.className = 'qkey';
      btn.textContent = k.label;
      if (k.title) btn.title = k.title;
      btn.addEventListener('click', () => {
        if (k.hotkey) sendHotkey(k.hotkey);
        else sendRaw(k.data);
        focusPrimaryInput();
      });
      grid.appendChild(btn);
    });
  }

  function initQuickKeys() {
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
  }

  function isEditableTarget(el) {
    if (!el || !(el instanceof HTMLElement)) return false;
    if (el.isContentEditable) return true;
    const tag = (el.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select';
  }

  function keyToToken(e) {
    const key = e.key;
    if (!key) return null;
    const lower = key.toLowerCase();
    if (/^f([1-9]|1[0-2])$/.test(lower)) return lower;

    const special = {
      control: 'ctrl',
      shift: 'shift',
      alt: 'alt',
      meta: 'meta',
      arrowup: 'up',
      arrowdown: 'down',
      arrowleft: 'left',
      arrowright: 'right',
      escape: 'esc',
      enter: 'enter',
      tab: 'tab',
      backspace: 'backspace',
      delete: 'delete',
      home: 'home',
      end: 'end',
      pageup: 'pgup',
      pagedown: 'pgdn',
      insert: 'insert',
      ' ': 'space',
    };
    if (special[lower]) return special[lower];
    if (key.length === 1) return lower;
    return null;
  }

  function initGlobalKeydown({ onF1 }) {
    window.addEventListener('keydown', (e) => {
      keyLog('keydown', {
        key: e.key,
        code: e.code,
        ctrl: e.ctrlKey,
        alt: e.altKey,
        shift: e.shiftKey,
        meta: e.metaKey,
        target: e.target && e.target.tagName,
      });

      if (e.key === 'F1') {
        e.preventDefault();
        if (typeof onF1 === 'function') onF1();
        keyLog('handled: help toggle');
        return;
      }

      if (isEditableTarget(e.target)) {
        keyLog('ignored: editable target');
        return;
      }

      const ws = getWs && getWs();
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        keyLog('ignored: websocket not open', ws ? ws.readyState : 'no-ws');
        return;
      }

      const token = keyToToken(e);
      if (!token) {
        keyLog('ignored: no token mapping for key', e.key);
        return;
      }

      if (token === 'shift' || token === 'ctrl' || token === 'alt' || token === 'meta') {
        flashVkByToken(token);
        keyLog('ignored: modifier-only key', token);
        return;
      }

      const mods = [];
      if (e.ctrlKey) mods.push('ctrl');
      if (e.altKey) mods.push('alt');
      if (e.metaKey) mods.push('win');
      if (e.shiftKey && token.length > 1) mods.push('shift');

      if (mods.length > 0) {
        e.preventDefault();
        const combo = mods.concat(token).join('+');
        keyLog('sendHotkey from keydown', combo);
        sendHotkey(combo);
        return;
      }

      if (e.key.length === 1) {
        e.preventDefault();
        keyLog('sendRaw from keydown', JSON.stringify(e.key));
        sendRaw(e.key);
        return;
      }

      e.preventDefault();
      keyLog('sendHotkey from keydown', token);
      sendHotkey(token);
    }, true);
  }

  function initVirtualKeyboard() {
    const _vkMods = new Set();

    const META_LABEL = () => {
      const targetOS = getTargetOS();
      if (targetOS === 'macos') return '⌘ Cmd';
      if (targetOS === 'linux') return '❖ Super';
      return '⊞ Win';
    };

    function updateMetaLabel() {
      document.querySelectorAll('.vkbd-key[data-mod="meta"]').forEach(el => {
        el.textContent = META_LABEL();
      });
    }

    function refreshModHighlights() {
      document.querySelectorAll('.vkbd-key[data-mod]').forEach(el => {
        const mod = el.dataset.mod;
        el.classList.toggle('mod-on', _vkMods.has(mod));
      });
    }

    function toggleMod(modName) {
      if (_vkMods.has(modName)) {
        _vkMods.delete(modName);
        refreshModHighlights();
        const agentKey = modName === 'meta' ? 'win' : modName;
        sendHotkey(agentKey);
      } else {
        _vkMods.add(modName);
        refreshModHighlights();
      }
    }

    function sendVkKey(keyName) {
      if (!keyName) return;
      const parts = [..._vkMods];
      const mapped = parts.map(m => m === 'meta' ? 'win' : m);
      mapped.push(keyName === ' ' ? 'space' : keyName);
      sendHotkey(mapped.join('+'));
      _vkMods.clear();
      refreshModHighlights();
    }

    const vkbd = document.getElementById('vkbd');
    if (!vkbd) return { updateMetaLabel };

    vkbd.querySelectorAll('.vkbd-key').forEach(el => {
      el.addEventListener('click', () => {
        const mod = el.dataset.mod;
        if (mod) {
          toggleMod(mod);
          return;
        }

        const key = el.dataset.key;
        if (_vkMods.has('shift') && el.dataset.shift) {
          _vkMods.delete('shift');
          sendHotkey(el.dataset.shift);
          refreshModHighlights();
        } else {
          sendVkKey(key);
        }
      });

      if (el.dataset.shift) {
        const mainLabel = el.dataset.label || el.dataset.key;
        el.innerHTML = `<span class="vkbd-shift-label">${el.dataset.shift}</span>${mainLabel}`;
      } else {
        el.textContent = el.dataset.label || el.dataset.key || '';
      }
    });

    vkbd.classList.remove('hidden');
    updateMetaLabel();
    refreshModHighlights();
    return { updateMetaLabel };
  }

  let updateMetaLabelRef = () => {};

  function init({ onF1 }) {
    initQuickKeys();
    initGlobalKeydown({ onF1 });
    const vk = initVirtualKeyboard();
    updateMetaLabelRef = vk.updateMetaLabel || (() => {});
    initResizeSplitter();
  }

  function initResizeSplitter() {
    const splitter = document.getElementById('resize-splitter');
    const terminalWrap = document.getElementById('terminal-wrap');
    if (!splitter || !terminalWrap) return;

    let isResizing = false;
    let startY = 0;
    let startScreenHeight = 0;

    // Load saved heights from localStorage
    const savedScreenHeight = localStorage.getItem('km_screen_height');
    const savedKeyboardHeight = localStorage.getItem('km_keyboard_height');
    if (savedScreenHeight) {
      terminalWrap.style.setProperty('--screen-height', savedScreenHeight);
    }
    if (savedKeyboardHeight) {
      terminalWrap.style.setProperty('--keyboard-height', savedKeyboardHeight);
    }

    splitter.addEventListener('mousedown', (e) => {
      isResizing = true;
      startY = e.clientY;
      const styles = window.getComputedStyle(terminalWrap);
      startScreenHeight = parseInt(styles.getPropertyValue('--screen-height') || '200px');
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      splitter.style.opacity = '1';
    });

    function handleMouseMove(e) {
      if (!isResizing) return;
      const deltaY = e.clientY - startY;
      const newScreenHeight = Math.max(180, Math.min(startScreenHeight + deltaY, window.innerHeight - 300));
      terminalWrap.style.setProperty('--screen-height', newScreenHeight + 'px');
      localStorage.setItem('km_screen_height', newScreenHeight + 'px');
    }

    function handleMouseUp() {
      isResizing = false;
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      splitter.style.opacity = '';
    }
  }

  function handleAgentPlatform(newOS) {
    if (!newOS || newOS === 'unknown' || newOS === getTargetOS()) return false;
    setTargetOS(newOS);
    localStorage.setItem('km_target_os', newOS);
    applyDefaultMacrosForOS(newOS);
    renderSysTab();
    updateMetaLabelRef();
    return true;
  }

  return {
    init,
    renderSysTab,
    updateMetaLabel: () => updateMetaLabelRef(),
    handleAgentPlatform,
    flashVkByToken,
    flashVkByCombo,
    flashVkByRawData,
  };
}
