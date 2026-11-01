// What the toolbar popup shows for a given state of the extension. Plain data in, plain data out, so it can be tested without a browser.
/** status: { enabled, connected, paired, pairing, tabs } as the service worker reports it. `chat` says whether the side chat can be opened: on, connected, and a Lumina tab to open it beside. */
export function describe(status) {
  const s = status || {};
  if (!s.enabled) return { text: s.paired ? 'Off. Lumina cannot use this browser.' : 'Not connected to Lumina yet.', button: s.paired ? 'Turn on' : '', askCode: !s.paired, tone: 'off' };
  if (s.pairing && !s.connected) return { text: 'Connecting to Lumina…', button: 'Turn off', askCode: false, tone: 'wait' };
  if (!s.connected) return { text: 'On, waiting for Lumina…', button: 'Turn off', askCode: false, tone: 'wait' };
  return { text: 'On. Lumina can open and use tabs in this browser.', button: 'Turn off', askCode: false, tone: 'on', chat: Array.isArray(s.tabs) && s.tabs.length > 0 };
}

/** Which Lumina tab to open the side chat beside: the one in front if it is one of ours, else the newest. -> tab id or null. */
export function chatTab(status, activeTabId) {
  const tabs = Array.isArray(status?.tabs) ? status.tabs : [];
  return tabs.includes(activeTabId) ? activeTabId : tabs.length ? tabs[tabs.length - 1] : null;
}
