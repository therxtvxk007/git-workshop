# CLAUDE.md — standing orders for every Claude Code session in this repo

This repo is shared between two people, each running their own Claude Code
instance on their own machine. Chat history does NOT travel between machines —
the files in this repo are the ONLY memory the two Claude instances share.

## Session routine (every session, both machines)

1. **Start of session:** run `git pull` before doing anything else. This is how
   you receive decisions and results made on the other machine.
2. **During the session:** any decision, result, or rejection that matters must
   be written into the right doc (see below) — not left in chat. If it only
   exists in chat, the other machine will never know about it.
3. **End of session:** update `HANDOFF.md` status, then commit and push
   everything in one go. Never end a session with unpushed work.

## Ownership split (avoid conflicts)

- Each collaborator owns their own files/directories — agree on the split in
  `HANDOFF.md` and stick to it.
- Never let both machines edit the same file between syncs. If a conflict does
  happen, git will flag it rather than silently losing work — resolve it
  together, don't force-push over it.

## What travels via git vs. what doesn't

| Travels via git                  | Doesn't travel (workaround)                          |
|----------------------------------|------------------------------------------------------|
| All code and all `.md` docs      | Chat sessions (write outcomes into docs instead)     |
| This file (both Claudes read it) | Claude's per-machine memory (this file substitutes)  |
| Dependency manifests             | Environments/venvs (each machine rebuilds its own)   |

## Where things are documented

- `HANDOFF.md` — current status: what exists, what's verified, who owns what,
  and what's next. Read it right after pulling; update it right before pushing.
