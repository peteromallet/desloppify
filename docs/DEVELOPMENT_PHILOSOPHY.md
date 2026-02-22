# Development Philosophy

This is a tool for agents. That shapes everything about how we build it.

## Agent-first

The primary user is an AI coding agent, not a human. The CLI output, the scoring model, the state format — all of it is optimized for agent consumption. Humans interact with it, but when there's a tradeoff between agent effectiveness and human UX, agent wins.

## No compatibility promise

Agents don't care about API stability the way human integrations do. We change things when we find a better way to do them. If you need a fixed contract, pin a version or fork. Migration shims are fine but they get a short removal window — we don't carry dead weight.

## The score is the point

The whole thing exists to give agents a north-star they can optimize toward. We collect objective signals, ask subjective questions, and combine them into one score. That score is an external objective — agents are already trained to optimize toward goals, and we're giving them a goal that happens to mean "make this codebase genuinely good."

## The score has to be honest

This is the thing we care about most. If an agent can game the score to 100 without actually improving anything, the tool is worthless. So we put a lot of effort into making sure score improvement tracks real quality improvement:

- Attestation requirements on resolution — agents have to describe what they actually did
- Wontfix still counts against strict score — you can't dismiss your way to a perfect number
- Subjective assessments are cross-checked — if scores land suspiciously close to targets, they get flagged or reset
- Subjective findings are weighted heavily (60% of total) because that's where real quality lives

## Language-agnostic

The scoring model and the core engine don't know about any specific language. Language-specific stuff lives in plugins. The principles and scoring intent stay the same whether you're scanning TypeScript, Python, or Rust. Currently 28 languages, and the plugin framework makes adding more straightforward.

## Architectural boundaries

We keep a few rules concrete so the codebase stays workable as it grows:

- Command entry files are thin orchestrators — behavior lives in focused modules underneath them
- Dynamic imports only happen in designated extension points (`languages/__init__.py`, `hook_registry.py`)
- Persisted state is owned by `state.py` and `engine/_state/` — command modules read and write through those APIs, they don't invent their own persisted fields
- Major boundaries have regression tests so refactors don't silently break things
