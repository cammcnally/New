---
name: ml-trading-pipeline-architecture
description: Use when planning, implementing, or refactoring any part of a Python machine-learning trading pipeline so the work stays aligned to end-to-end research integrity, reproducibility, and execution realism.
---

# ML Trading Pipeline Architecture

## Purpose

Keep every implementation aligned to the end-state repository outcome: a production-grade Python ML trading pipeline that is point-in-time correct, benchmark-aware, reproducible, and strategy-reporting capable.

## Use this skill when

- adding a new subsystem
- refactoring data/model/reporting code
- deciding where logic belongs
- integrating notebooks into reusable modules
- resolving architectural drift
- coordinating multiple agents on separate tasks

## Core architecture principles

### 1. Treat the system as a chain, not isolated files

Every component should fit into:
data -> features -> labels -> model -> signal diagnostics -> strategy evaluation -> report artifacts

### 2. Separate surfaces cleanly

Prefer explicit surfaces such as:

- raw data
- cleaned/normalized data
- derived features
- model artifacts
- benchmark/risk-free artifacts
- report artifacts

### 3. Prefer canonical artifacts over implicit computation

If an important intermediate is reused, persist it.
Do not force downstream code to recreate critical semantics informally.

### 4. Push notebooks to the edge

Use notebooks for exploration, demos, and inspection.
Put durable logic in modules.

### 5. Optimize for reproducibility

Every important run should have:

- config
- seed policy
- run id
- data snapshot id
- benchmark context
- output artifacts

## What success looks like

A new engineer or agent should be able to answer:

- what goes in
- what comes out
- what assumptions were made
- how the result was validated
- how to rerun it

## Default design decisions

- centralize contracts rather than duplicating local assumptions
- prefer clear module boundaries over “smart” hidden coupling
- name artifacts deterministically
- keep business semantics explicit in code, not only in prose
