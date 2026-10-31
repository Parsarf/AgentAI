// What the toolbar popup shows for a given state of the extension. Plain data in, plain data out, so it can be tested without a browser.
/** status: { enabled, connected, paired, pairing } as the service worker reports it. */
export function describe(status) {
  const s = status || {};
  if (!s.enabled) return { text: s.paired ? 'Off. Lumina cannot use this browser.' : 'Not connected to Lumina yet.', button: s.paired ? 'Turn on' : '', askCode: !s.paired, tone: 'off' };
  if (s.pairing && !s.connected) return { text: 'Connecting to Lumina…', button: 'Turn off', askCode: false, tone: 'wait' };
  if (!s.connected) return { text: 'On, waiting for Lumina…', button: 'Turn off', askCode: false, tone: 'wait' };
  return { text: 'On. Lumina can open and use tabs in this browser.', button: 'Turn off', askCode: false, tone: 'on' };
}
