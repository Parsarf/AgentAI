import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createBoard, restore, serialize, STORAGE_KEY } from '../src/board.mjs';

function memory(initial = null) {
  const values = new Map(initial === null ? [] : [[STORAGE_KEY, initial]]);
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test('add trims, rejects blank, keeps duplicate titles and unique IDs including zero', () => {
  const board = createBoard(memory());
  assert.deepEqual(board.add('  '), { ok: false, error: 'Enter a task title.' });
  assert.equal(board.tasks.length, 0);
  assert.deepEqual(board.add('  Repeat  ').task, { id: 0, title: 'Repeat', completed: false });
  assert.deepEqual(board.add('Repeat').task, { id: 1, title: 'Repeat', completed: false });
  assert.deepEqual(board.tasks.map(task => task.id), [0, 1]);
});

test('toggle and delete affect only selected ID; filters do not mutate collection', () => {
  const board = createBoard(memory());
  board.add('same'); board.add('same'); board.add('third');
  assert.equal(board.toggle(0), true);
  assert.deepEqual(board.filtered('completed').map(task => task.id), [0]);
  assert.deepEqual(board.filtered('active').map(task => task.id), [1, 2]);
  assert.deepEqual(board.filtered('all').map(task => task.id), [0, 1, 2]);
  assert.deepEqual(board.tasks.map(task => task.completed), [true, false, false]);
  assert.equal(board.delete(1), true);
  assert.deepEqual(board.tasks.map(task => task.id), [0, 2]);
  assert.equal(board.toggle(1), false);
  assert.equal(board.delete(1), false);
  assert.deepEqual(board.filtered('active').map(task => task.id), [2]);
});

test('namespaced serialization and restore retain completion and advance IDs', () => {
  const storage = memory();
  const board = createBoard(storage);
  board.add('Alpha'); board.add('Beta'); board.toggle(0);
  assert.equal(storage.values.has(STORAGE_KEY), true);
  assert.deepEqual(restore(storage.values.get(STORAGE_KEY)), board.tasks);
  const restored = createBoard(storage);
  assert.deepEqual(restored.tasks, [{ id: 0, title: 'Alpha', completed: true }, { id: 1, title: 'Beta', completed: false }]);
  assert.equal(restored.add('Gamma').task.id, 2);
  assert.equal(serialize([{ id: 0, title: 'A', completed: false }]), '{"version":1,"tasks":[{"id":0,"title":"A","completed":false}]}');
});

test('corrupt saved data is not silently overwritten; explicit replace works', () => {
  const storage = memory('{bad json');
  const board = createBoard(storage);
  assert.equal(board.persistence, 'corrupt');
  assert.match(board.explanation, /not been overwritten/);
  board.add('session');
  assert.equal(storage.values.get(STORAGE_KEY), '{bad json');
  assert.equal(board.replaceSavedData(), true);
  assert.equal(board.persistence, 'ok');
  assert.deepEqual(restore(storage.values.get(STORAGE_KEY)), [{ id: 0, title: 'session', completed: false }]);
  for (const raw of ['{"version":1,"tasks":[{"id":0,"title":"a","completed":false},{"id":0,"title":"b","completed":false}]}', '{"version":2,"tasks":[]}', '{"version":1,"tasks":[{"id":0,"title":" ","completed":false}]}']) {
    assert.equal(createBoard(memory(raw)).persistence, 'corrupt');
  }
});

test('unavailable storage does not crash; writes are explained', () => {
  const bad = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  const board = createBoard(bad);
  assert.equal(board.persistence, 'unavailable');
  assert.equal(board.add('works in memory').ok, true);
  assert.equal(board.toggle(0), true);
  assert.equal(board.delete(0), true);
  assert.match(board.explanation, /may not survive/);
});

test('malicious title remains data and app uses text-only DOM assignment', () => {
  const title = '<img src=x onerror=alert(1)>';
  const board = createBoard(memory());
  board.add(title);
  assert.equal(board.tasks[0].title, title);
  const app = fs.readFileSync(new URL('../src/app.mjs', import.meta.url), 'utf8');
  assert.match(app, /text\.textContent = task\.title/);
  assert.doesNotMatch(app, /innerHTML|outerHTML|insertAdjacentHTML/);
});

test('failed write leaves previously valid saved data intact and warns', () => {
  const saved = serialize([{ id: 0, title: 'saved', completed: false }]);
  const storage = { getItem: () => saved, setItem() { throw new Error('quota'); } };
  const board = createBoard(storage);
  assert.equal(board.add('new').task.id, 1);
  assert.equal(board.persistence, 'unavailable');
  assert.match(board.explanation, /may not survive/);
  assert.equal(storage.getItem(), saved);
});
