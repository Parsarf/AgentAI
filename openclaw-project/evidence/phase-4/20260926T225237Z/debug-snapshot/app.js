class TaskStore {
  constructor() { this._tasks = new Map(); this._next = 0; }
  add(title) {
    if (typeof title !== "string" || !title.trim()) throw new TypeError("title required");
    const t = { id: this._next, title: title.trim(), done: false };
    this._tasks.set(t.id, t);
    this._next += 1;
    return t;
  }
  toggle(id) { const t = this._get(id); t.done = !t.done; return t; }
  remove(id) { this._get(id); this._tasks.delete(id); }
  _get(id) {
    const t = this._tasks.get(id);
    if (t === undefined) throw new RangeError(`no task with id ${id}`);
    return t;
  }
  items() { return [...this._tasks.values()]; }
  filter(view) {
    if (view === "all") return this.items();
    if (view !== "active" && view !== "completed") throw new RangeError(`unknown view ${view}`);
    const wantDone = view === "completed";
    return this.items().filter((t) => t.done === wantDone);
  }
}
module.exports = { TaskStore };
