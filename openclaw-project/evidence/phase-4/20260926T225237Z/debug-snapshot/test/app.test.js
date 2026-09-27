const test = require("node:test");
const assert = require("node:assert/strict");
const { TaskStore } = require("../app.js");

test("add rejects blank titles", () => {
  const s = new TaskStore();
  assert.throws(() => s.add("   "), TypeError);
});

test("add, toggle, remove lifecycle", () => {
  const s = new TaskStore();
  const a = s.add("write spec");
  const b = s.add("ship it");
  assert.deepEqual(s.items().map((t) => t.title), ["write spec", "ship it"]);
  s.toggle(b.id);
  assert.equal(s.filter("completed").length, 1);
  s.remove(a.id);
  assert.deepEqual(s.items().map((t) => t.id), [b.id]);
  assert.throws(() => s.remove(99), RangeError);
});

test("filter active/completed on nonzero ids", () => {
  const s = new TaskStore();
  s.add("warmup");
  const a = s.add("first");
  const b = s.add("second");
  s.remove(0);
  s.toggle(b.id);
  assert.deepEqual(s.filter("active").map((t) => t.id), [a.id]);
  assert.deepEqual(s.filter("completed").map((t) => t.id), [b.id]);
  assert.equal(s.filter("all").length, 2);
});

test("filter includes task zero in its matching state", () => {
  const s = new TaskStore();
  const zero = s.add("zero");
  assert.deepEqual(s.filter("active").map((t) => t.id), [zero.id]);
  s.toggle(zero.id);
  assert.deepEqual(s.filter("completed").map((t) => t.id), [zero.id]);
});
