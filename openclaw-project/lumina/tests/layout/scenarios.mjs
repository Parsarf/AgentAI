// What the layout sweep visits: every route of the app and the states of it that change the layout (an open thread, a dialog, a menu, the assistant panel, a
// permission prompt, a failed or stopped task). `fx` names the fixture that serves it (see tests/layout-browser.mjs). A state's `act` drives the page there; `undo`
// puts it back before the next state. Add the new route or state here when you add one to the app.
const key = k => async page => { await page.keyboard.press(k); await page.waitForTimeout(250); };
const click = (selector, { nth = 0 } = {}) => async page => { await page.locator(selector).nth(nth).click({ timeout: 6000 }); await page.waitForTimeout(300); };
const escape = async page => { await page.keyboard.press('Escape'); await page.waitForTimeout(200); };
const firstTask = async (base, conversation) => {
  const r = await fetch(base + '/v1/work', { signal: AbortSignal.timeout(10000) }); const tasks = (await r.json()).tasks || [];
  return (tasks.find(t => t.conversation_id === conversation) || tasks[0] || {}).id || 'none';
};

export function scenarios() {
  const frameStress = ['thread', 'list', 'calendar', 'files', 'settings', 'dashboard', 'table'].map(kind => ({ fx: 'mail', name: `frame-stress-${kind}`, path: `/app/frame-stress/${kind}` }));
  const settings = ['general', 'assistant', 'access', 'integrations', 'usage', 'account'].map(s => ({ fx: 'mail', name: `settings-${s}`, path: `/app/settings/${s}`, ready: '.set-card, .panel' }));
  const workChats = ['unconfirmed', 'verified', 'failed', 'plain', 'permission', 'handoff', 'stopped'].map(c => ({ fx: 'work', name: `task-chat-${c}`, path: `/app/chat/${c}`, ready: '.composer' }));
  return [
    // The whole application on the real server code (tests/preview_mail.py).
    { fx: 'mail', name: 'login', path: '/app/', anon: true, ready: 'form, input' },
    { fx: 'mail', name: 'chat-new', path: '/app/', ready: '.composer',
      states: [{ name: 'default' }, { name: 'long-draft', act: async page => { await page.locator('.composer textarea').fill('A long draft that keeps going. '.repeat(40) + 'https://example.com/' + 'unbroken-segment-'.repeat(30)); await page.waitForTimeout(200); } }] },
    { fx: 'mail', name: 'home', path: '/app/home', ready: '.zone-canvas',
      states: [{ name: 'default' }, { name: 'command-bar', act: key('ControlOrMeta+k'), undo: escape }, { name: 'help-sheet', act: key('?'), undo: escape },
        { name: 'assistant', act: key('ControlOrMeta+j'), undo: key('ControlOrMeta+j') }, { name: 'context-hidden', act: key('ControlOrMeta+b'), undo: key('ControlOrMeta+b') }] },
    { fx: 'mail', name: 'history', path: '/app/history' },
    { fx: 'mail', name: 'activity', path: '/app/activity', ready: '.zone-canvas' },
    { fx: 'mail', name: 'files', path: '/app/files', ready: '.zone-canvas' },
    { fx: 'mail', name: 'knowledge', path: '/app/knowledge', ready: '.zone-canvas' },
    { fx: 'mail', name: 'inbox', path: '/app/inbox', ready: '.mail-row-open',
      states: [{ name: 'list' }, { name: 'thread-open', act: click('.mail-row-open'), ready: '.mail-thread, .mail-message, iframe' },
        { name: 'compose', act: async page => { await page.keyboard.press('Escape'); await page.locator('.mail-compose-button').first().click({ timeout: 6000 }); await page.waitForTimeout(400); }, undo: escape }] },
    { fx: 'mail', name: 'calendar', path: '/app/calendar', ready: '.hub-event, .hub-week, .cal-new',
      states: [{ name: 'week' }, { name: 'new-event', act: click('.cal-new'), ready: '[role="dialog"]', undo: escape }] },
    ...settings,
    ...frameStress,
    { fx: 'mail', name: 'gen-gallery', path: '/app/gen-gallery' },

    // Every kind of task, on the real state code (tests/preview_work.py).
    ...workChats,
    { fx: 'work', name: 'task-activity', path: '/app/activity', ready: '.zone-canvas' },
    { fx: 'work', name: 'task-record', path: async base => `/app/activity/${await firstTask(base, 'failed')}`, ready: '.zone-canvas' },
    { fx: 'work', name: 'task-live', path: async base => `/app/live/${await firstTask(base, 'unconfirmed')}`, ready: '.zone-canvas' },
    { fx: 'work', name: 'task-live-handoff', path: async base => `/app/live/${await firstTask(base, 'handoff')}`, ready: '.zone-canvas' },

    // Content made to break layouts, from the mock API with a frozen clock (dev-mock.mjs; tests/layout-browser.mjs starts it): a 140-character chat title, unbroken
    // words and URLs, code and a wide table, a failed task, 400 threads, five-figure unread counts, long task titles in Activity, file names in a narrow panel.
    { fx: 'mock', name: 'stress-chat', path: '/app/chat/c4', ready: '.composer' },
    { fx: 'mock', name: 'stress-task-chat', path: '/app/chat/c1', ready: '.composer' },
    { fx: 'mock', name: 'stress-home', path: '/app/home', ready: '.zone-canvas' },
    { fx: 'mock', name: 'stress-activity', path: '/app/activity', ready: '.table' },
    { fx: 'mock', name: 'stress-files', path: '/app/files', ready: '.zone-canvas' },
    { fx: 'mock', name: 'stress-inbox', path: '/app/inbox', ready: '.mail-row-open', states: [{ name: 'list' }, { name: 'thread-open', act: click('.mail-row-open'), ready: 'iframe' }] },
    { fx: 'mock', name: 'stress-calendar', path: '/app/calendar', ready: '.hub-event' },

    // Long, wide and many-turn conversations (tests/preview_chat.py).
    ...['working', 'completed', 'long', 'multiple', 'overflow'].map(c => ({ fx: 'chat', name: `chat-${c}`, path: `/app/chat/${c}`, ready: '.composer' })),
    { fx: 'chat', name: 'chat-working-motion', path: '/app/chat/working', ready: '.composer', motion: true, viewports: v => v.width === 390 || v.width === 1280 },
  ];
}
