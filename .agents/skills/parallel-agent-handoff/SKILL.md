---
name: parallel-agent-handoff
description: Use when multiple agents or worktrees are touching the same repo so their work remains aligned to the same end-state and does not drift.
---

# Parallel Agent Handoff

## Purpose

Keep multiple agents working toward the same finished repository, even when they are solving different subproblems.

## Use this skill when

- work is split across multiple agents
- there are parallel worktrees
- a task depends on another unresolved task
- one agent is changing contracts while another changes consumers
- a handoff note is needed

## Required handoff format

Every meaningful parallel task should write or update a handoff note containing:

### Task

What this agent was responsible for.

### North-star link

Which repo outcome this task serves.

### Files touched

Exact files changed or intended to be changed.

### Contracts assumed

Schemas, artifact names, benchmark semantics, data assumptions, rule invariants.

### Decisions made

What was chosen and why.

### Open dependencies

What another agent must preserve or complete.

### Verification

What was tested or still needs testing.

## Coordination rules

- Do not silently change shared semantics.
- If you change a contract, update the handoff.
- If your work depends on missing architecture, state the dependency explicitly.
- When in doubt, optimize for downstream compatibility and repo coherence.
