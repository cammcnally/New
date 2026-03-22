# Start Here

> **This master file supersedes both prior versions (original bundle and hardened bundle). On conflict, Section A governs.**

This bundle is the **authoritative implementation contract** for Cursor to build a single-file institutional trading-research pipeline centered on `Pipeline.py`.

---

## Section A — Hardened spec

### Non-negotiable build standard

This bundle is **not** satisfied by a scaffold. Cursor must not return:
- placeholders
- random stand-ins
- mocked metrics
- commented-out core stages
- "v1 now, v2 later" language
- partial implementations presented as complete

The task is complete only if Cursor produces an **end-to-end runnable implementation** against the real panel and all major claims are backed by:
- code-path evidence in the repository
- or primary-library documentation where library-specific behavior is introduced

### What this bundle contains

1. **01_MASTER_CURSOR_PROMPT.md**  
   Main Composer instruction. Use this first.

2. **02_PIPELINE_BLUEPRINT.md**  
   Institutional design spec: chronology, labeling, modeling, feature discovery, policy layer, ranking, seeds, IC, volatility clustering, and promotion rules.

3. **03_FEATURE_LIBRARY_SPEC.md**  
   The complete candidate feature-library contract for a 1-hour bar system targeting a holding period of roughly **2 trading days to 3 trading weeks**.

4. **04_OUTPUT_FILE_POLICY.md**  
   Folder structure, overwrite defaults, checkpointing, atomic writes, stale-output invalidation, and file-class rules.

5. **05_SUBAGENTS_RULES_COMMANDS.md**  
   Required Cursor subagents, rules, commands, and overwrite behavior.

6. **06_VALIDATION_AND_ACCEPTANCE.md**  
   The acceptance test. If implementation fails any section here, it is not complete.

7. **feature_registry_template.json**  
   Reference schema for the implemented feature registry.

8. **Subagents and rules**  
   Cursor-native files live in `.cursor/agents/` and `.cursor/rules/` as local compatibility shims. The canonical authority lives in `AGENTS.md`, the Phase 1 docs, and the control-plane runtime. Keep the local Cursor layer aligned by regenerating it from tracked repo sources. **Operational extensions** (pipeline-watcher, verifier) remain automatic: pipeline-watcher on pipeline failure, verifier after code edits.

### Build philosophy

- Keep implementation centered on **one main file: `Pipeline.py`**
- Keep file creation **clean, limited, and overwrite-oriented**
- Preserve **resume / checkpointing**
- Build **staged discovery**, not brute-force raw subset search
- Produce a **ranked strategy library**
- Produce a **human-readable final report**
- Use **walk-forward, out-of-sample, event-safe validation**
- Enforce **train-only transforms** for any learned pruning, ranking, clustering, ablation, or subset selection step

### Recommended use

1. Give **01_MASTER_CURSOR_PROMPT.md** to Cursor Composer.
2. If Cursor needs more precision, feed **02** through **06** in order.
3. Subagents and rules may appear in `.cursor/agents/` and `.cursor/rules/` for local Cursor ergonomics, but they are compatibility projections rather than canonical repo policy.
4. Reject any implementation that uses placeholders, random metrics, or fake completeness.

---

## Section B — Legacy clarifications & context

- The original bundle described this as a **single-file, feature-discovery and strategy-library trading pipeline** with a **strict output policy that avoids file explosion**. The hardened spec above encodes these goals.
- The original referenced **templates/** for ready-to-use Cursor subagent/rule/command templates. Cursor-native files may still be rendered into `.cursor/` locally, but the canonical control-plane policy now lives in tracked repo files.
- **Design intent** (from original): Keep file creation clean and overwrite-oriented; preserve resume/checkpointing; build a feature-discovery workflow, not just raw importance dumps; produce a ranked strategy library; produce a human-readable final report; use walk-forward, out-of-sample, event-safe validation.
