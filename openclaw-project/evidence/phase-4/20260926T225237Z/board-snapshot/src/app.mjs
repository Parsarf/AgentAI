import { createBoard, FILTERS } from './board.mjs';

const storage = {
  getItem: key => window.localStorage.getItem(key),
  setItem: (key, value) => window.localStorage.setItem(key, value)
};
const board = createBoard(storage);
const form = document.querySelector('#task-form');
const title = document.querySelector('#task-title');
const titleError = document.querySelector('#title-error');
const list = document.querySelector('#task-list');
const empty = document.querySelector('#empty-state');
const notice = document.querySelector('#storage-notice');
const replace = document.querySelector('#replace-data');
const count = document.querySelector('#task-count');
let filter = 'all';

function render() {
  list.replaceChildren();
  const visible = board.filtered(filter);
  for (const task of visible) {
    const li = document.createElement('li');
    li.className = 'task-row';
    const label = document.createElement('label');
    label.className = 'task-label';
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = task.completed;
    check.setAttribute('aria-label', `Complete ${task.title}`);
    check.addEventListener('change', () => { board.toggle(task.id); render(); });
    const text = document.createElement('span');
    text.textContent = task.title;
    if (task.completed) text.className = 'done';
    label.append(check, text);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'delete-button';
    remove.textContent = 'Delete';
    remove.setAttribute('aria-label', `Delete ${task.title}`);
    remove.addEventListener('click', () => { board.delete(task.id); render(); });
    li.append(label, remove);
    list.append(li);
  }
  empty.hidden = visible.length !== 0;
  empty.textContent = filter === 'all' ? 'No tasks yet. Add one above.' :
    filter === 'active' ? 'No active tasks.' : 'No completed tasks.';
  count.textContent = `${board.tasks.length} total · ${board.tasks.filter(task => !task.completed).length} active`;
  notice.hidden = board.persistence === 'ok';
  notice.textContent = board.explanation;
  replace.hidden = board.persistence !== 'corrupt';
  for (const button of document.querySelectorAll('[data-filter]')) {
    const active = button.dataset.filter === filter;
    button.setAttribute('aria-pressed', String(active));
    button.classList.toggle('selected', active);
  }
}

form.addEventListener('submit', event => {
  event.preventDefault();
  const result = board.add(title.value);
  if (!result.ok) {
    titleError.textContent = result.error;
    title.setAttribute('aria-invalid', 'true');
    title.focus();
    return;
  }
  title.value = '';
  titleError.textContent = '';
  title.removeAttribute('aria-invalid');
  title.focus();
  render();
});
title.addEventListener('input', () => { titleError.textContent = ''; title.removeAttribute('aria-invalid'); });
for (const button of document.querySelectorAll('[data-filter]')) {
  if (!FILTERS.includes(button.dataset.filter)) continue;
  button.addEventListener('click', () => { filter = button.dataset.filter; render(); });
}
replace.addEventListener('click', () => { board.replaceSavedData(); render(); });
render();
