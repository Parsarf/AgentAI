# Private Task Board

A dependency-free task board. Tasks stay in this browser's local storage; there are no accounts or external services.

## Start

```sh
node server.mjs
```

Open http://127.0.0.1:3000. The server binds only to 127.0.0.1. Set `PORT=3001` to use another port. Stop with Ctrl+C.

## Test

```sh
node --test tests/*.test.mjs
```

No install step is needed. Node.js 24 is the tested runtime.

If saved data is unreadable, the app does not overwrite it. The on-screen **Replace saved data** button explicitly permits replacing it with the current session's tasks. If storage is unavailable, tasks remain usable until reload and the page displays a warning.
