# TaskStore fixture spec

In-memory task store used by the Phase 4 debugging exercise.

## Behavior contract

- add(title): trims; blank/whitespace -> TypeError; assigns sequential ids
  starting at 0.
- toggle(id) / remove(id): unknown id -> RangeError.
- filter(view):
  - "all" -> every task, insertion order.
  - "active" -> tasks with done === false.
  - "completed" -> tasks with done === true.
  - anything else -> RangeError.
- Tasks with id 0 are ordinary tasks: every view that matches them by state
  must include them. An id of 0 must never cause a task to be dropped.

## Acceptance

- `node --test` passes on the untouched baseline.
- The fix must be demonstrated by a regression test for the id-0 exclusion
  that FAILS on the original code and PASSES after the fix, with the
  neighboring tests unchanged and passing.
