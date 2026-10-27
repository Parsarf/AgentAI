# Safety console

The Safety menu is drawn as a text-only terminal window (`root@lumina: ~`): black, soft white, muted gray, one monospace font, categories as an expandable `▼ [1] Title` tree with `├─ └─ │` branches,
switches as `[x] Title   [ON]` / `[ ] Title   [OFF]`, a `[?] What does this do?` line under every switch, and `[ Apply Changes ]` / `[ Discard Changes ]` as plain text. It has its own grayscale palette on
purpose (`styles/safety.css` is the one stylesheet the design check lets hold colours). Nothing in it is invented: the categories, switches, values and notes all come from the server.

The switches for Lumina's safety features, with two views behind a tab bar at the top:

- **My account**: the switches as they apply to this account only.
- **All users** (the owner only): the default every account gets. An account's own setting wins over it; an account can exempt itself from an "off for everyone".

Who gets the menu is decided by the server: the owner (`AGENTAI_SAFETY_OWNER_ACCOUNT`) and any account the owner has granted it. Everyone else gets a 404, so the UI shows nothing. A granted account sees
only **My account** (no tab bar, no access list). The owner manages grants in the **All users** view ("Who can open this menu"). Everything that changes something needs the account password.

Some switches are shown but cannot be changed here (`lock` in the API): **shared** (server-wide, set in deploy files), **core** (tenant isolation, vault encryption, audit log: always on) and
**privacy** protections, which can be switched off for your own account but never for everyone. The wording for these is in `notesOf` (`src/lib/safety.ts`) so every design says the same thing.
The switch list, which switches code actually reads (`wired`) and the rules above all come from the server (`platform/agentai_platform/safety.py`, `platform/accounts/safety.py`); this folder adds no rules.

## Where things live (so the look can change without touching the behaviour)

| Layer | File | Knows about |
|---|---|---|
| Data and rules | `src/lib/safety.ts` | types, the draft/diff helpers, the wording of the notes, the API calls (switches and access). No React, no CSS. |
| Explanations | `src/lib/safetyHelp.ts` | the four-part "What does this do?" text for every switch (what it does, why, while on, while off), written from what the code does. A backend test fails if a switch has none. |
| Behaviour | `src/lib/useSafety.ts` | one hook returning a `SafetyModel` (account, state, scope, draft per scope, busy, error, `done`, access, `show/hide/setScope/toggle/setAll/setMinutes/discard/apply/grant/revoke`). No markup. It never holds the password: the view passes it to the one call that needs it. |
| Parts | `src/components/safety/ConsoleParts.tsx` | text-only pieces: `Category`, `Setting`, the explanation block, `DurationRow` (text list + custom minutes), `PasswordPrompt` (masked, inline), `Action`, `Note` |
| Window | `src/components/safety/SafetyDialog.tsx` | the terminal window: title bar, header, view tabs, the tree, Access (owner, All users), Review Configuration, the pending-changes bar. Holds only view state: which categories and explanations are open, the duration list, the password prompt. |
| Entry | `src/components/safety/SafetyButton.tsx` | the only thing the rest of the app imports; renders nothing for accounts without access |
| Look | `src/styles/safety.css` | the monochrome terminal palette and layout, `con-*` classes |

The sidebar mounts `<SafetyButton />` inside its `<nav className="nav">` (`.nav button` already styles it like the other items; `.lbl` folds away with the sidebar).

## Behaviour worth knowing

- **Saving** asks for the password in a masked field right in the tree, only after Apply Changes (or Give access / Remove). A wrong password or a failure shows `[!] ...` inline and keeps every choice;
  `[+] Configuration saved successfully.` appears only after the server confirmed, and the console stays open. The password lives only in that field.
- **Opening an explanation never touches the switch.** Categories and explanations are independent, several can be open, and they are remembered only while the console is open.
- **Escape** closes the innermost open thing: the duration list, then the password prompt, then the console.
- **Disable duration** is the only editable value (the server has no other numbers to set): a text list of the server's choices plus `Custom...` for any whole number of minutes from 1 to 10080.
- **Window controls**: close, minimize (title bar only) and maximize all work.
- Each view (My account, All users) keeps its own unsaved choices while you switch between them; applying All users refreshes My account.

## Remodelling

- **New look:** change `styles/safety.css` (and `ConsoleParts.tsx` / `SafetyDialog.tsx` for structure). The behaviour, the words and the server rules do not move.
- **New layout (a page, a settings section):** write a view that takes `useSafety()`'s model and `helpFor(feature)`; `SafetyButton` only needs to call `model.show`.
- Hooks for tests and restyling: `data-safety="button" | "layer" | "scopes" | "list" | "access" | "review" | "duration" | "password"` and `data-group="<group key>"`.
- Keep: the password prompt (changes are refused without it), the "not enforced yet" note on switches the code does not read, the reasons shown for locked switches, the plain explanations, and the plain error messages.
