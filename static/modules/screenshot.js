export function createScreenshotModule({ getWs, incSent, focusPrimaryInput }) {
  const screenshotOverlay = document.getElementById('screenshot-overlay');
  let lastScreenshotData = null;
  let autoRefreshInterval = null;
  let autoRefreshRate = 0; // 0 = off

  function renderPinnedScreenshot(data) {
    const pinnedImg = document.getElementById('screenshot-pinned-img');
    const pinnedMeta = document.getElementById('screenshot-pinned-meta');
    const pinnedEmpty = document.getElementById('screenshot-pinned-empty');
    if (!pinnedImg || !pinnedMeta || !pinnedEmpty || !data) return;
    pinnedImg.src = data.data;
    pinnedImg.style.display = 'block';
    pinnedMeta.textContent = data.width + '×' + data.height;
    pinnedEmpty.style.display = 'none';
  }

  function clearPinnedScreenshot(message = 'Click Refresh to retrieve target screen') {
    const pinnedImg = document.getElementById('screenshot-pinned-img');
    const pinnedMeta = document.getElementById('screenshot-pinned-meta');
    const pinnedEmpty = document.getElementById('screenshot-pinned-empty');
    if (pinnedImg) {
      pinnedImg.removeAttribute('src');
      pinnedImg.style.display = 'none';
    }
    if (pinnedMeta) pinnedMeta.textContent = '';
    if (pinnedEmpty) {
      pinnedEmpty.textContent = message;
      pinnedEmpty.style.display = 'block';
    }
  }

  function requestPinnedScreenshot() {
    const ws = getWs && getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    clearPinnedScreenshot('Retrieving screenshot…');
    if (screenshotOverlay) screenshotOverlay.classList.remove('show');
    ws.send(JSON.stringify({ type: 'screenshot_request' }));
    if (typeof incSent === 'function') incSent();
  }

  function startAutoRefresh(intervalSeconds) {
    stopAutoRefresh();
    if (intervalSeconds <= 0) return;
    autoRefreshRate = intervalSeconds;
    autoRefreshInterval = setInterval(() => {
      requestPinnedScreenshot();
    }, intervalSeconds * 1000);
  }

  function stopAutoRefresh() {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = null;
    }
    autoRefreshRate = 0;
  }

  function onScreenshot(msg) {
    const spinner = document.getElementById('screenshot-spinner');
    const errDiv = document.getElementById('screenshot-err');
    const img = document.getElementById('screenshot-img');
    const meta = document.getElementById('screenshot-meta');

    if (spinner) spinner.style.display = 'none';
    if (errDiv) errDiv.style.display = 'none';
    if (img) {
      img.src = msg.data;
      img.style.display = 'block';
    }
    if (meta) meta.textContent = msg.width + '×' + msg.height;

    lastScreenshotData = msg;
    renderPinnedScreenshot(msg);
    if (screenshotOverlay) screenshotOverlay.classList.remove('show');
  }

  function onScreenshotError(msg) {
    const spinner = document.getElementById('screenshot-spinner');
    const errDiv = document.getElementById('screenshot-err');
    const pinnedEmpty = document.getElementById('screenshot-pinned-empty');
    const pinnedMeta = document.getElementById('screenshot-pinned-meta');
    const text = '⚠ ' + (msg.error || 'Screenshot failed');

    if (spinner) spinner.style.display = 'none';
    if (errDiv) {
      errDiv.textContent = text;
      errDiv.style.display = 'block';
    }
    if (pinnedEmpty) {
      pinnedEmpty.textContent = text;
      pinnedEmpty.style.display = 'block';
    }
    if (pinnedMeta) pinnedMeta.textContent = '';
    if (screenshotOverlay) screenshotOverlay.classList.remove('show');
  }

  function init() {
    const btnScreenshot = document.getElementById('btn-screenshot');
    const btnRefresh = document.getElementById('btn-screenshot-refresh');
    const btnPinnedRefresh = document.getElementById('btn-screenshot-refresh-pinned');
    const btnClose = document.getElementById('btn-screenshot-close');
    const btnPin = document.getElementById('btn-screenshot-pin');
    const btnClear = document.getElementById('btn-screenshot-unpin');
    const autoRefreshSelect = document.getElementById('auto-refresh-select');

    if (btnScreenshot) btnScreenshot.onclick = requestPinnedScreenshot;
    if (btnRefresh) btnRefresh.onclick = requestPinnedScreenshot;
    if (btnPinnedRefresh) btnPinnedRefresh.onclick = requestPinnedScreenshot;

    if (autoRefreshSelect) {
      autoRefreshSelect.onchange = (e) => {
        const intervalSeconds = parseFloat(e.target.value);
        startAutoRefresh(intervalSeconds);
      };
    }

    if (btnPin) {
      btnPin.onclick = () => {
        if (!lastScreenshotData) return;
        renderPinnedScreenshot(lastScreenshotData);
        if (screenshotOverlay) screenshotOverlay.classList.remove('show');
        if (typeof focusPrimaryInput === 'function') focusPrimaryInput();
      };
    }

    if (btnClear) {
      btnClear.onclick = () => {
        clearPinnedScreenshot();
        if (typeof focusPrimaryInput === 'function') focusPrimaryInput();
      };
    }

    if (btnClose) {
      btnClose.onclick = () => {
        if (screenshotOverlay) screenshotOverlay.classList.remove('show');
        if (typeof focusPrimaryInput === 'function') focusPrimaryInput();
      };
    }

    if (screenshotOverlay) {
      screenshotOverlay.addEventListener('click', (e) => {
        if (e.target !== screenshotOverlay) return;
        screenshotOverlay.classList.remove('show');
        if (typeof focusPrimaryInput === 'function') focusPrimaryInput();
      });
    }
  }

  return {
    init,
    onScreenshot,
    onScreenshotError,
    requestPinnedScreenshot,
    renderPinnedScreenshot,
    clearPinnedScreenshot,
    startAutoRefresh,
    stopAutoRefresh,
  };
}
