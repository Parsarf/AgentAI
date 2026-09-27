export const STORAGE_KEY = 'private-task-board:v1';
export const FILTERS = ['all', 'active', 'completed'];

export function serialize(tasks) {
  return JSON.stringify({ version: 1, tasks });
}

export function restore(raw) {
  const data = JSON.parse(raw);
  if (!data || data.version !== 1 || !Array.isArray(data.tasks)) throw new Error('Unsupported saved tasks');
  const ids = new Set();
  return data.tasks.map(task => {
    if (!task || !Number.isSafeInteger(task.id) || task.id < 0 || ids.has(task.id) ||
        typeof task.title !== 'string' || !task.title.trim() || task.title !== task.title.trim() ||
        typeof task.completed !== 'boolean') throw new Error('Invalid saved task');
    ids.add(task.id);
    return { id: task.id, title: task.title, completed: task.completed };
  });
}

export function createBoard(storage, key = STORAGE_KEY) {
  let tasks = [];
  let persistence = 'ok';
  let explanation = '';
  try {
    const raw = storage.getItem(key);
    if (raw !== null) tasks = restore(raw);
  } catch (error) {
    persistence = error instanceof SyntaxError || error?.message === 'Unsupported saved tasks' || error?.message === 'Invalid saved task' ? 'corrupt' : 'unavailable';
    explanation = persistence === 'corrupt'
      ? 'Saved tasks could not be read. They have not been overwritten. Choose “Replace saved data” to start fresh.'
      : 'Storage is unavailable. Changes in this session may not survive a reload.';
  }
  let nextId = tasks.reduce((max, task) => Math.max(max, task.id + 1), 0);
  const snapshot = () => tasks.map(task => ({ ...task }));
  function persist() {
    if (persistence === 'corrupt') return;
    try {
      storage.setItem(key, serialize(tasks));
      persistence = 'ok';
      explanation = '';
    } catch {
      persistence = 'unavailable';
      explanation = 'Storage is unavailable. Changes in this session may not survive a reload.';
    }
  }
  return {
    get tasks() { return snapshot(); },
    get persistence() { return persistence; },
    get explanation() { return explanation; },
    add(title) {
      const trimmed = String(title).trim();
      if (!trimmed) return { ok: false, error: 'Enter a task title.' };
      if (!Number.isSafeInteger(nextId)) return { ok: false, error: 'Task limit reached.' };
      const task = { id: nextId++, title: trimmed, completed: false };
      tasks.push(task);
      persist();
      return { ok: true, task: { ...task } };
    },
    toggle(id) {
      const task = tasks.find(item => item.id === id);
      if (!task) return false;
      task.completed = !task.completed;
      persist();
      return true;
    },
    delete(id) {
      const index = tasks.findIndex(item => item.id === id);
      if (index < 0) return false;
      tasks.splice(index, 1);
      persist();
      return true;
    },
    filtered(filter) {
      if (!FILTERS.includes(filter)) throw new Error('Unknown filter');
      return snapshot().filter(task => filter === 'all' || task.completed === (filter === 'completed'));
    },
    replaceSavedData() {
      if (persistence !== 'corrupt') return false;
      try {
        storage.setItem(key, serialize(tasks));
        persistence = 'ok';
        explanation = '';
        return true;
      } catch {
        persistence = 'unavailable';
        explanation = 'Storage is unavailable. Changes in this session may not survive a reload.';
        return false;
      }
    }
  };
}
