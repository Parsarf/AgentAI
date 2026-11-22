// Real-browser check of the Calendar's layout on the real server code, with the stand-in calendars of tests/preview_mail.py (a dense week: four all-day entries on one
// day, long titles that end in their course, ten-minute entries, deadlines with no length, events that overlap). No real account, no network beyond localhost.
//   npm run build
//   ../platform/.venv/bin/python tests/preview_mail.py &            (https://127.0.0.1:5183)
//   node tests/calendar-browser.mjs
// It measures what the page draws, at a desktop and a laptop size, in a narrow window, with the side column dragged and hidden, and at 200% zoom: every event tall
// enough for its title and none cut off, none covering another, each at its true time, the headings, the all-day section and the columns in line while the grid
// scrolls both ways, the toolbar's controls in reach, the side column scrolling by itself, and the New event dialog (keyboard, what is wrong said at its field, a long
// calendar name, the grid left where it was). Screenshots go to CALENDAR_QA_OUTPUT (default /tmp/lumina-calendar).
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { BASE, connectGoogle, connectMicrosoft, session, until } from './preview-session.mjs';

const out = process.env.CALENDAR_QA_OUTPUT || '/tmp/lumina-calendar';
await mkdir(out, { recursive: true });
const SIZES = { desktop: { width: 1440, height: 900 }, laptop: { width: 1280, height: 720 }, narrow: { width: 700, height: 800 }, zoom: { width: 720, height: 450, scale: 2 }, phone: { width: 390, height: 780 } };
const results = []; let failed = 0;
let current = null;
const check = async (name, fn) => { try { const note = await fn(); results.push(`ok    ${name}${note ? `  (${note})` : ''}`); } catch (e) { failed++; results.push(`FAIL  ${name}\n      ${String(e.message ?? e).split('\n')[0].slice(0, 400)}`);
  for (let i = 0; i < 3 && current && await current.locator('[role="dialog"], [role="menu"]').count().catch(() => 0); i++) await current.keyboard.press('Escape').catch(() => {}); } };   // a failed check leaves nothing open for the next

const first = await session(SIZES.desktop);
await connectGoogle(first.page); await connectMicrosoft(first.page);
await until(first.page, () => fetch('/v1/hub', { credentials: 'same-origin' }).then(r => r.json()).then(r => r.calendars.length >= 4 && r.calendars.every(c => c.filled)), null, { timeout: 60000, polling: 1500 });

/** What the week grid draws, measured: every box in CSS pixels, relative to the window. */
const measure = page => page.evaluate(() => {
  const box = e => { const r = e.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; };
  const grid = document.querySelector('.hub-week'); const hour = parseFloat(getComputedStyle(grid).getPropertyValue('--hour'));
  const heads = [...grid.querySelectorAll('.hub-week-day')], all = [...grid.querySelectorAll('.hub-week-allday:not(.gutter)')], cols = [...grid.querySelectorAll('.hub-day-col')];
  const cut = e => [...e.children].filter(c => !c.classList.contains('hub-resize')).some(c => c.getBoundingClientRect().bottom > e.getBoundingClientRect().bottom + 0.5 && c.getBoundingClientRect().top < e.getBoundingClientRect().bottom - 0.5);
  return { hour, grid: box(grid), scroll: { left: grid.scrollLeft, top: grid.scrollTop, width: grid.scrollWidth, height: grid.scrollHeight, clientWidth: grid.clientWidth },
    gutter: box(grid.querySelector('.hub-hours')), corner: box(grid.querySelector('.hub-week-corner')),
    days: heads.map((h, i) => ({ day: h.dataset.col, head: box(h), allDay: box(all[i]), col: box(cols[i]),
      allDayChips: [...all[i].querySelectorAll('.hub-event')].map(c => ({ ...box(c), text: c.querySelector('b').textContent, lineCut: cut(c), titleHeight: c.querySelector('b').getBoundingClientRect().height })),
      more: [...all[i].querySelectorAll('.hub-more')].map(m => ({ ...box(m), text: m.textContent })),
      timed: [...cols[i].querySelectorAll('.hub-event')].map(c => ({ ...box(c), label: c.getAttribute('aria-label'), brief: c.classList.contains('brief'), point: c.classList.contains('point'), lineCut: cut(c),
        title: box(c.querySelector('b')), offset: (c.getBoundingClientRect().top - cols[i].getBoundingClientRect().top) / hour })),
      folds: [...cols[i].querySelectorAll('.hub-more-wrap.timed')].map(box) })) };
});
const overlap = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
const open = async (page, size) => { await page.goto(BASE + '/app/calendar', { waitUntil: 'domcontentloaded' });
  if (size === 'phone') await page.getByRole('button', { name: 'Week', exact: true }).click();
  await page.locator('.hub-week').waitFor(); await page.locator('.hub-day-col .hub-event').first().waitFor(); await page.waitForTimeout(600); };

async function week(page, size) {
  await open(page, size);
  await page.locator('.hub-week').evaluate(el => { el.scrollTop = 7.5 * 48; }); await page.waitForTimeout(200);
  await page.screenshot({ path: `${out}/${size}-week.png` });
  const m = await measure(page);
  const monday = m.days[0].day, friday = m.days[4], sunday = m.days[6], tuesday = m.days[1], wednesday = m.days[2], thursday = m.days[3];
  await check(`${size}: every all-day event is one whole line of text, none squeezed or cut`, () => {
    const chips = m.days.flatMap(d => d.allDayChips); assert.ok(chips.length >= 4, `only ${chips.length} all-day events drawn`);
    for (const c of chips) { assert.ok(c.height >= 22, `"${c.text}" is ${c.height}px tall`); assert.ok(c.titleHeight >= 15 && !c.lineCut, `"${c.text}" is cut`); }
    return `${chips.length} events, ${Math.min(...chips.map(c => c.height))}px each`;
  });
  await check(`${size}: Friday's four and Sunday's all-day events are all there, drawn or behind "+N more", inside their own section`, () => {
    for (const d of [friday, sunday]) for (const c of [...d.allDayChips, ...d.more]) assert.ok(c.bottom <= d.allDay.bottom + 0.5 && c.top >= d.allDay.top - 0.5, `${d.day}: "${c.text}" leaves the all-day section`);
    const hidden = d => (d.more[0] ? Number(/\+(\d+)/.exec(d.more[0].text)[1]) : 0);
    assert.equal(friday.allDayChips.length + hidden(friday), 4); assert.equal(sunday.allDayChips.length + hidden(sunday), 3);
    return `Friday ${friday.allDayChips.length} drawn${hidden(friday) ? ` +${hidden(friday)} more` : ''}, Sunday ${sunday.allDayChips.length} drawn${hidden(sunday) ? ` +${hidden(sunday)} more` : ''}`;
  });
  await check(`${size}: short events and deadlines sit at their true time with a title that can be read`, () => {
    const all = m.days.flatMap(d => d.timed); const at = (label, hours) => { const e = all.filter(x => x.label.startsWith(label)); assert.ok(e.length, `"${label}" is not drawn`); for (const x of e) assert.ok(Math.abs(x.offset - hours) < 0.03, `"${x.label}" is at ${x.offset.toFixed(2)}h, not ${hours}h`); return e; };
    const classwork = at('Classwork 2', 12.5), lab = at('Submit Buoyancy Lab', 14); at('Dentist', 8.25); at('PHYS 101 Lecture', 9);
    for (const e of [...classwork, ...lab]) { assert.ok(e.height >= 20, `"${e.label}" is ${e.height}px tall`); assert.ok(e.title.height >= 15 && e.title.bottom <= e.bottom + 0.5 && !e.lineCut, `"${e.label}" has its title cut`); assert.ok(e.title.width >= 28, `"${e.label}" has ${e.title.width}px for its title`); }
    assert.ok(lab.every(e => e.point) && classwork.every(e => e.brief && !e.point));
    return `${classwork.length} classwork entries ${classwork[0].height.toFixed(0)}px, deadline ${lab[0].height.toFixed(0)}px`;
  });
  await check(`${size}: no event covers another, and every one keeps room for a title`, () => {
    let pairs = 0;
    for (const d of m.days) { const boxes = [...d.timed, ...d.folds];
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) { pairs++; assert.ok(!overlap(boxes[i], boxes[j]), `${d.day}: "${boxes[i].label ?? '+N'}" and "${boxes[j].label ?? '+N'}" overlap`); }
      for (const e of d.timed) { assert.ok(e.left >= d.col.left - 0.5 && e.right <= d.col.right + 0.5, `"${e.label}" leaves its day`); assert.ok(e.width >= 44, `"${e.label}" is only ${e.width.toFixed(0)}px wide`); assert.ok(!e.lineCut, `"${e.label}" has a line cut in half`); } }
    const drawn = tuesday.timed.filter(e => e.offset >= 13 && e.offset < 15).length;
    return `${pairs} pairs; Tuesday 1 PM: ${drawn} drawn${tuesday.folds.length ? ' and a "+N"' : ''}; Wednesday 3 PM: ${wednesday.timed.filter(e => e.offset >= 15 && e.offset < 16).length} drawn${wednesday.folds.length ? ' and a "+N"' : ''}`;
  });
  await check(`${size}: the headings, the all-day section and the columns are in line, and a day is wide enough to read`, () => {
    for (const d of m.days) { for (const part of [d.allDay, d.col]) assert.ok(Math.abs(part.left - d.head.left) < 0.6 && Math.abs(part.width - d.head.width) < 0.6, `${d.day}: a column is ${part.width}px at ${part.left}, its heading ${d.head.width}px at ${d.head.left}`);
      assert.ok(d.head.width >= 111.5, `${d.day} is ${d.head.width}px wide`); }
    return `${m.days[0].head.width.toFixed(0)}px a day${m.scroll.width > m.scroll.clientWidth + 1 ? ', scrolls sideways' : ''}`;
  });
  await check(`${size}: scrolled down and sideways, the headings stay on top, the hours at the left, and everything stays in line`, async () => {
    await page.locator('.hub-week').evaluate(el => { el.scrollTop = 600; el.scrollLeft = 150; }); await page.waitForTimeout(200);
    const s = await measure(page);
    assert.ok(Math.abs(s.days[0].head.top - s.grid.top) < 1.5 && Math.abs(s.corner.left - s.grid.left) < 1.5 && Math.abs(s.gutter.left - s.grid.left) < 1.5, 'a heading or the hours moved away');
    assert.ok(Math.abs(s.days[0].allDay.top - s.days[0].head.bottom) < 1.5, 'the all-day section left the headings');
    for (const d of s.days) for (const part of [d.allDay, d.col]) assert.ok(Math.abs(part.left - d.head.left) < 0.6, `${d.day} is out of line by ${part.left - d.head.left}px`);
    await page.locator('.hub-week').evaluate(el => { el.scrollLeft = 0; });
    return s.scroll.left ? `moved ${s.scroll.left}px sideways` : 'no sideways room needed';
  });
  await check(`${size}: moving through time, the views and New event are all on screen and can be pressed`, async () => {
    const view = page.viewportSize(); const seen = [];
    for (const name of ['Today', 'Earlier', 'Later', 'Day', 'Week', 'Month', 'Agenda', 'New event']) {
      const b = await page.getByRole('button', { name, exact: true }).first().boundingBox(); assert.ok(b, `${name} is not shown`);
      assert.ok(b.x >= 0 && b.x + b.width <= view.width + 0.5 && b.y >= 0 && b.y + b.height <= view.height, `${name} is off the screen`); assert.ok(b.width >= 24 && b.height >= 24, `${name} is ${b.width}x${b.height}`); seen.push(b); }
    for (let i = 0; i < seen.length; i++) for (let j = i + 1; j < seen.length; j++) assert.ok(!overlap({ left: seen[i].x, right: seen[i].x + seen[i].width, top: seen[i].y, bottom: seen[i].y + seen[i].height }, { left: seen[j].x, right: seen[j].x + seen[j].width, top: seen[j].y, bottom: seen[j].y + seen[j].height }), 'two controls overlap');
    const title = await page.locator('.wsp-title').evaluate(e => ({ cut: e.scrollWidth > e.clientWidth + 1, text: e.textContent }));
    assert.ok(!title.cut, `the heading "${title.text}" is cut`);
    const search = await page.getByRole('searchbox', { name: 'Search events' }).count() ? 'a search field' : await page.getByRole('button', { name: 'Search events' }).count() ? 'a search button' : null; assert.ok(search, 'no search');
    const more = await page.locator('.wsp-toolbar').getByRole('button', { name: 'More', exact: true }).count();
    return `"${title.text}", ${search}${more ? ', a More menu' : ', Refresh shown'}`;
  });
  return m;
}

// -- each size --------------------------------------------------------------------------------------------------------------------------------------------------
for (const size of Object.keys(SIZES)) {
  const { context, page } = size === 'desktop' ? first : await first.again(SIZES[size]);
  current = page;
  await week(page, size);
  if (size === 'desktop') {
    await check('desktop: "+N more" on a crowded all-day section opens the full list for that day, by keyboard, and a choice opens the event', async () => {
      await page.setViewportSize({ width: 1440, height: 560 }); await page.waitForTimeout(400);                    // a shorter window shows fewer all-day rows
      const more = page.getByRole('button', { name: /more all day on Friday, November 20, 2026\. Show all 4/ });
      await more.focus(); await page.keyboard.press('Enter');
      const items = await page.getByRole('menu').getByRole('menuitem').allTextContents(); assert.equal(items.length, 4, items.join(' | '));
      await page.screenshot({ path: `${out}/desktop-more.png` });
      await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
      const panel = page.getByLabel('Event details'); await panel.getByRole('heading').waitFor();
      const words = await panel.innerText(); assert.match(words, /PHYS 101-003 Fall 2026|ENGL 204-001 Fall 2026|ENGR 110-002 Fall 2026/); assert.match(words, /Friday, November 20, 2026, all day/);
      await page.keyboard.press('Escape'); await page.setViewportSize(SIZES.desktop); await page.waitForTimeout(300);
      return items[0].slice(0, 40);
    });
    await check('desktop: a short event opens with its whole title, its course and its time, by mouse and by keyboard', async () => {
      const chip = page.getByRole('button', { name: 'Submit Buoyancy Lab [PHYS 101-003 Fall 2026], 2:00 PM' });
      assert.equal(await chip.getAttribute('title'), 'Submit Buoyancy Lab [PHYS 101-003 Fall 2026] · 2:00 PM');
      await chip.click(); const panel = page.getByLabel('Event details');
      await panel.getByRole('heading', { name: 'Submit Buoyancy Lab' }).waitFor(); assert.match(await panel.innerText(), /PHYS 101-003 Fall 2026[\s\S]*Thursday, November 19, 2026, 2:00 PM/);
      await page.screenshot({ path: `${out}/desktop-event.png` });
      await page.keyboard.press('Escape'); await panel.waitFor({ state: 'detached' });
      const other = page.getByRole('button', { name: /^Classwork 21: Fluids and pressure/ }); await other.focus(); await page.keyboard.press('Enter');
      await page.getByLabel('Event details').getByRole('heading', { name: 'Classwork 21: Fluids and pressure' }).waitFor(); await page.keyboard.press('Escape');
    });
    await check('desktop: a busy stretch that folds into "+N" lists what it stands for', async () => {
      const fold = page.locator('.hub-more-wrap.timed .hub-more').first();
      if (!await fold.count()) return 'nothing folded at this width';
      await fold.click(); const items = await page.getByRole('menu').getByRole('menuitem').allTextContents(); assert.ok(items.length >= 1);
      await page.keyboard.press('Escape'); return items.map(i => i.replace(/\d.*$/, '')).join(', ').slice(0, 80);
    });
    await check('desktop: the side column dragged narrow and wide, and hidden: the toolbar and the grid follow the room they are given', async () => {
      const split = page.locator('.split').first(); const b = await split.boundingBox(); const notes = [];
      for (const [name, dx] of [['wide', 220], ['narrow', -400]]) {
        await page.mouse.move(b.x + b.width / 2, b.y + 200); await page.mouse.down(); await page.mouse.move(b.x + b.width / 2 + dx, b.y + 200, { steps: 8 }); await page.mouse.up(); await page.waitForTimeout(400);
        const side = await page.locator('.zone-context').boundingBox(); const m = await measure(page);
        for (const d of m.days) assert.ok(Math.abs(d.col.left - d.head.left) < 0.6 && d.head.width >= 111.5, `${name}: ${d.day} out of line or too narrow`);
        const cut = await page.locator('.hub-calendar-row span:first-of-type').evaluateAll(els => els.filter(e => e.getBoundingClientRect().width < 30).length); assert.equal(cut, 0, `${name}: a calendar name has no room`);
        for (const n of ['Today', 'Week', 'New event']) assert.ok(await page.getByRole('button', { name: n, exact: true }).first().isVisible(), `${name}: ${n} is gone`);
        await page.screenshot({ path: `${out}/desktop-side-${name}.png` }); notes.push(`${name} ${side.width.toFixed(0)}px: ${m.days[0].head.width.toFixed(0)}px a day`);
        const again = await split.boundingBox(); b.x = again.x; b.y = again.y;
      }
      await page.getByRole('button', { name: 'Hide calendars' }).click(); await page.waitForTimeout(400);
      const m = await measure(page); assert.ok(m.days[0].head.width > 150, 'the grid did not take the freed room'); await page.screenshot({ path: `${out}/desktop-side-hidden.png` });
      assert.ok(await page.getByRole('searchbox', { name: 'Search events' }).isVisible(), 'with the side column hidden there is room for the search field');
      await page.getByRole('button', { name: 'Show calendars' }).click(); notes.push(`hidden: ${m.days[0].head.width.toFixed(0)}px a day`);
      return notes.join('; ');
    });
  }
  if (size === 'zoom' || size === 'laptop') {
    await check(`${size}: the side column scrolls by itself, down to the last calendar`, async () => {
      if (!await page.locator('.zone-context').count()) await page.getByRole('button', { name: 'Show calendars' }).click();
      const body = page.locator('.zone-context .zone-body, .sheet.zone-sheet .sheet-body').first(); await body.waitFor();
      const before = await page.locator('.hub-week').evaluate(e => e.scrollTop);
      const s = await body.evaluate(e => { e.scrollTop = e.scrollHeight; return { scrolls: e.scrollHeight > e.clientHeight + 1, top: e.scrollTop }; });
      const last = page.locator('.hub-calendar-row').last(); assert.ok(await last.isVisible());
      const b = await last.boundingBox(), view = page.viewportSize(); assert.ok(b.y + b.height <= view.height + 0.5, 'the last calendar cannot be reached');
      assert.equal(await page.locator('.hub-week').evaluate(e => e.scrollTop), before, 'the grid moved with the side column');
      await page.screenshot({ path: `${out}/${size}-side.png` });
      if (await page.locator('.sheet.zone-sheet').count()) await page.keyboard.press('Escape');
      return s.scrolls ? `scrolled ${s.top}px to "${(await last.innerText()).trim()}"` : 'everything fits without scrolling';
    });
  }
  if (size === 'narrow' || size === 'zoom' || size === 'phone') {
    await check(`${size}: the week scrolls sideways, Day and Agenda are one press away, and what was put away is in the More menu`, async () => {
      const m = await measure(page); assert.ok(m.scroll.width > m.scroll.clientWidth + 1, 'the week does not scroll');
      await page.locator('.wsp-toolbar').getByRole('button', { name: 'More', exact: true }).click(); const items = await page.getByRole('menu').getByRole('menuitem').allTextContents(); await page.keyboard.press('Escape');
      assert.ok(items.some(i => /Refresh/.test(i)) && items.some(i => /Change timezone/.test(i)), items.join(' | '));
      await page.getByRole('button', { name: 'Search events' }).click(); await page.getByRole('searchbox', { name: 'Search events' }).fill('Buoyancy'); await page.keyboard.press('Enter');
      await page.getByText('Events matching').waitFor(); await page.screenshot({ path: `${out}/${size}-search.png` }); await page.getByRole('button', { name: 'Close search' }).click();
      await page.getByRole('button', { name: 'Day', exact: true }).click(); await page.locator('.hub-week.day').waitFor(); const day = await measure(page);
      assert.ok(day.days.length === 1 && day.scroll.width <= day.scroll.clientWidth + 1, 'the day view scrolls sideways'); await page.screenshot({ path: `${out}/${size}-day.png` });
      await page.getByRole('button', { name: 'Agenda', exact: true }).click(); await page.locator('.hub-agenda').waitFor(); await page.screenshot({ path: `${out}/${size}-agenda.png` });
      await page.getByRole('button', { name: 'Week', exact: true }).click(); await page.locator('.hub-week.week').waitFor();
      return `More: ${items.map(i => i.replace(/America.*$/, '')).join(', ')}`;
    });
  }

  // -- the New event dialog -------------------------------------------------------------------------------------------------------------------------------------
  await check(`${size}: New event is a dialog over the calendar; the grid stays exactly where it was, opened and closed`, async () => {
    await page.locator('.hub-week').evaluate(el => { el.scrollTop = 433; el.scrollLeft = Math.min(37, el.scrollWidth - el.clientWidth); }); await page.waitForTimeout(150);
    const before = await page.locator('.hub-week').evaluate(el => ({ top: el.scrollTop, left: el.scrollLeft, y: el.getBoundingClientRect().top, h: el.getBoundingClientRect().height }));
    const opener = page.getByRole('button', { name: 'New event', exact: true }); await opener.click();
    const dialog = page.getByRole('dialog', { name: 'New event' }); await dialog.waitFor(); await page.waitForTimeout(350);
    const during = await page.locator('.hub-week').evaluate(el => ({ top: el.scrollTop, left: el.scrollLeft, y: el.getBoundingClientRect().top, h: el.getBoundingClientRect().height }));
    assert.deepEqual(during, before, 'the grid moved when the dialog opened');
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('placeholder')), 'Add a title', 'the title does not have the focus');
    const view = page.viewportSize(); const d = await dialog.boundingBox(); assert.ok(d.x >= 0 && d.y >= 0 && d.x + d.width <= view.width + 0.5 && d.y + d.height <= view.height + 0.5, 'the dialog leaves the window');
    for (const name of ['Cancel', 'Create event']) { const b = await dialog.getByRole('button', { name, exact: true }).boundingBox(); assert.ok(b && b.y + b.height <= view.height + 0.5 && b.y >= d.y, `${name} is out of reach`); }
    const fields = await dialog.evaluate(el => [...el.querySelectorAll('.input')].map(i => { const r = i.getBoundingClientRect(), s = getComputedStyle(i); return { tag: i.tagName, type: i.type, h: r.height, w: r.width, right: r.right, radius: s.borderRadius, font: s.fontFamily.slice(0, 20) }; }));
    assert.ok(fields.length >= 7 && fields.every(f => f.h >= 38 && f.radius === '10px' && f.right <= d.x + d.width), `a field is not the shared input: ${JSON.stringify(fields.find(f => f.h < 38 || f.radius !== '10px'))}`);
    assert.equal(new Set(fields.map(f => f.font)).size, 1, 'the fields use different fonts');
    const labels = await dialog.evaluate(el => [...el.querySelectorAll('.field')].map(f => { const l = f.querySelector('label').getBoundingClientRect(), c = f.querySelector('.input').getBoundingClientRect(); return c.top - l.bottom; }));
    assert.ok(labels.every(gap => gap >= 3 && gap <= 12), `a label is ${labels.find(g => g < 3 || g > 12)}px from its field`);
    await page.screenshot({ path: `${out}/${size}-new.png` });
    const stacked = await dialog.evaluate(el => { const r = [...el.querySelectorAll('.field-row .field')].map(f => f.getBoundingClientRect()); return r.length > 1 && r[1].top > r[0].bottom - 1; });
    const scrolls = await dialog.locator('.sheet-body').evaluate(e => e.scrollHeight > e.clientHeight + 1);
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'detached' });
    assert.ok(await opener.evaluate(e => e === document.activeElement), 'the focus did not go back to New event');
    assert.deepEqual(await page.locator('.hub-week').evaluate(el => ({ top: el.scrollTop, left: el.scrollLeft, y: el.getBoundingClientRect().top, h: el.getBoundingClientRect().height })), before, 'the grid moved when the dialog closed');
    return `${d.width.toFixed(0)}x${d.height.toFixed(0)}${stacked ? ', fields stacked' : ''}${scrolls ? ', the form scrolls, actions stay' : ''}`;
  });
  if (size === 'desktop' || size === 'zoom') {
    await check(`${size}: the dialog by keyboard: Tab stays inside, what is wrong is said at its field, a long calendar name fits, Enter creates`, async () => {
      const opener = page.getByRole('button', { name: 'New event', exact: true }); await opener.focus(); await page.keyboard.press('Enter');
      const dialog = page.getByRole('dialog', { name: 'New event' }); await dialog.waitFor();
      const inside = () => page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'));
      for (let i = 0; i < 14; i++) { await page.keyboard.press('Tab'); assert.ok(await inside(), `Tab ${i + 1} left the dialog`); }
      for (let i = 0; i < 3; i++) { await page.keyboard.press('Shift+Tab'); assert.ok(await inside(), 'Shift+Tab left the dialog'); }
      const title = dialog.getByLabel('Title'); await title.focus(); await page.keyboard.press('Enter');                    // nothing typed yet
      const error = dialog.getByText('Give the event a title.'); await error.waitFor();
      const e = await error.boundingBox(), t = await title.boundingBox(); assert.ok(e.y >= t.y + t.height - 1 && e.y - (t.y + t.height) < 14, 'the error is not beside the title');
      assert.equal(await title.getAttribute('aria-invalid'), 'true'); assert.ok(await title.evaluate(el => el === document.activeElement));
      const picker = dialog.getByLabel('Calendar'); const names = await picker.locator('option').allTextContents();
      const long = names.find(n => n.length > 40); assert.ok(long, `no long calendar name among ${names.join(' | ')}`);
      await picker.selectOption({ label: long }); const p = await picker.boundingBox(), d = await dialog.boundingBox();
      assert.ok(p.x >= d.x && p.x + p.width <= d.x + d.width, 'the calendar picker leaves the dialog'); assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'the dialog scrolls sideways');
      await page.screenshot({ path: `${out}/${size}-new-long-name.png` });
      assert.ok(names.every(n => !/ · /.test(n)), 'a calendar is named with its account');
      await dialog.getByLabel('Ends').fill('08:00'); await dialog.getByText('It must end after it starts.').waitFor(); await page.screenshot({ path: `${out}/${size}-new-errors.png` });
      await dialog.getByLabel('Ends').fill('11:30'); await title.fill('Layout check'); await title.press('Enter');
      await dialog.waitFor({ state: 'detached' }); await page.getByText('The event was created.').waitFor();
      return `calendars: ${names.map(n => n.slice(0, 24)).join(' | ')}`;
    });
  }
  if (size !== 'desktop') await context.close();
}

// -- the rest of the app: the shared controls -----------------------------------------------------------------------------------------------------------------------
{
  const page = first.page; current = page;
  await check('Settings and Activity: the side lists have one row height, and the open section is marked', async () => {
    await page.goto(BASE + '/app/settings', { waitUntil: 'domcontentloaded' }); await page.getByRole('tab', { name: 'General' }).waitFor();
    const rows = await page.locator('.set-sections .files-folder').evaluateAll(els => els.map(e => ({ y: e.getBoundingClientRect().top, h: e.getBoundingClientRect().height, on: e.getAttribute('aria-selected') === 'true', bg: getComputedStyle(e).backgroundColor })));
    const pitch = rows[1].y - rows[0].y; assert.ok(pitch <= rows[0].h + 4, `the rows are ${pitch}px apart for ${rows[0].h}px rows`);
    const on = rows.find(r => r.on), off = rows.find(r => !r.on); assert.notEqual(on.bg, off.bg, 'the open section looks like the others');
    await page.screenshot({ path: `${out}/settings.png` });
    await page.goto(BASE + '/app/activity', { waitUntil: 'domcontentloaded' }); await page.locator('.act-filter-list .files-folder').first().waitFor();
    const acts = await page.locator('.act-filter-list').first().locator('.files-folder').evaluateAll(els => els.map(e => e.getBoundingClientRect().top));
    assert.ok(acts[1] - acts[0] <= rows[0].h + 4, `Activity's rows are ${acts[1] - acts[0]}px apart`); await page.screenshot({ path: `${out}/activity.png` });
    return `${pitch}px a row`;
  });
  await check('Home: an all-day event is on its own day', async () => {
    await page.goto(BASE + '/app/home', { waitUntil: 'domcontentloaded' }); const tile = page.locator('section, article').filter({ has: page.getByRole('heading', { name: 'Next meetings' }) }).last();
    await tile.getByText('Mum visiting').waitFor(); const row = await tile.locator('li').filter({ hasText: 'Mum visiting' }).innerText();
    assert.match(row, /Today, all day/, row.replace(/\s+/g, ' ')); await page.screenshot({ path: `${out}/home.png` });
  });
}
await first.browser.close();
console.log(results.join('\n'));
console.log(failed ? `\n${failed} of ${results.length} checks failed. Screenshots: ${out}` : `\nAll ${results.length} checks passed. Screenshots: ${out}`);
process.exit(failed ? 1 : 0);
