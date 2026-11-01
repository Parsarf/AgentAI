import { describe, chatTab } from './popup-model.js';

const $ = id => document.getElementById(id);
const ask = message => chrome.runtime.sendMessage(message);

async function render() {
  const status = await ask({ type: 'status' });
  const view = describe(status);
  $('status').textContent = view.text; $('status').dataset.tone = view.tone;
  $('pair').hidden = !view.askCode;
  $('toggle').hidden = !view.button; $('toggle').textContent = view.button;
  $('chat').hidden = !view.chat;
}

// Chrome opens a side panel only for a click, so it is opened here, straight from the button, beside a tab Lumina is working in.
$('chat').addEventListener('click', async () => {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  const tabId = chatTab(await ask({ type: 'status' }), active?.id);
  if (tabId === null) return;
  try { await chrome.sidePanel.open({ tabId }); window.close(); } catch { /* the tab went away: nothing to open beside */ }
});

$('toggle').addEventListener('click', async () => { await ask({ type: 'toggle' }); await render(); });
$('pair').addEventListener('submit', async e => {
  e.preventDefault();
  const error = $('error'); error.hidden = true;
  const reply = await ask({ type: 'pair', code: $('code').value });
  if (!reply || !reply.ok) { error.textContent = 'That is not a Lumina pairing code. It has 8 letters and numbers.'; error.hidden = false; return; }
  $('code').value = '';
  await render();
});

render();
setInterval(render, 1500);      // the link comes up a moment after pressing a button
