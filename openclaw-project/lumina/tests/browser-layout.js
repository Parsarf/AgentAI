// Real-browser regression assertions. Loaded only by preview_chat.py.
function check() {
  const bubble = document.querySelector('.bubble.you');
  if (!bubble) return;
  const failures = [];
  if (bubble.textContent === 'hey' && bubble.getBoundingClientRect().height > 60)
    failures.push('A one-line message expanded beyond its content height.');
  const strip = document.querySelector('.taskstrip');
  if (strip) failures.push('The removed Working card returned.');
  const thinking = document.querySelector('.agent-thinking');
  if (thinking && (thinking.getBoundingClientRect().height > 90 || Math.abs(thinking.getBoundingClientRect().left - document.querySelector('.thread').getBoundingClientRect().left) > 1))
    failures.push('The assistant thinking indicator is stretched or misaligned.');
  if (document.querySelector('.globe')) failures.push('An active conversation rendered decorative scenery.');
  if (document.documentElement.scrollWidth > innerWidth)
    failures.push('The conversation overflows the viewport horizontally.');
  const composer = document.querySelector('.chatpage .composer');
  const nav = document.querySelector('.side');
  if (composer && nav && innerWidth <= 960 && getComputedStyle(nav).position === 'fixed' && composer.getBoundingClientRect().bottom > nav.getBoundingClientRect().top - 1)
    failures.push('The composer overlaps the fixed mobile navigation.');
  const turns = [...document.querySelectorAll('.turn')];
  for (let i = 1; i < turns.length; i++) {
    if (turns[i].getBoundingClientRect().top < turns[i - 1].getBoundingClientRect().bottom - 1)
      failures.push('Conversation turns overlap.');
  }
  for (const p of document.querySelectorAll('.agent-response p')) {
    if (p.scrollWidth > p.clientWidth + 1) failures.push('Ordinary prose does not wrap.');
  }
  for (const pre of document.querySelectorAll('.agent-response pre')) {
    if (pre.getBoundingClientRect().width > document.querySelector('.thread').getBoundingClientRect().width + 1)
      failures.push('A code box widened the conversation.');
    if (getComputedStyle(pre).overflowX !== 'auto' || pre.tabIndex !== 0)
      failures.push('Code cannot be scrolled within its own focusable box.');
  }
  if (location.pathname.endsWith('/overflow') && document.querySelector('.agent-response') && !document.querySelector('.agent-response [role="img"]'))
    failures.push('The reported pie chart was left as raw JSON.');
  document.documentElement.dataset.layoutCheck = failures.length ? 'failed' : 'passed';
  document.documentElement.dataset.layoutFailures = failures.join(' ');
  if (failures.length) console.error('Chat layout regression:', failures);
}
let queued = false;
function schedule() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; check(); });
}
new MutationObserver(schedule).observe(document.getElementById('root'), { childList: true, subtree: true });
addEventListener('resize', schedule);
addEventListener('scroll', schedule, { passive: true });
schedule();
