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
  const turns = [...document.querySelectorAll('.turn')];
  for (let i = 1; i < turns.length; i++) {
    if (turns[i].getBoundingClientRect().top < turns[i - 1].getBoundingClientRect().bottom - 1)
      failures.push('Conversation turns overlap.');
  }
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
