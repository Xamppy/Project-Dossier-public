---
name: subagent-driven-development
description: "Execute plans via Agent-tool subagents (2-stage review)."
version: 1.1.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
metadata:
  hermes:
    tags: [delegation, subagent, implementation, workflow, parallel]
    related_skills: [writing-plans, requesting-code-review, test-driven-development]
---

# Subagent-Driven Development

## Overview

Execute implementation plans by dispatching fresh subagents per task with systematic two-stage review, using Claude Code's `Agent` tool.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration.

**Tool note:** this skill originally referenced `delegate_task` (a Hermes Agent-specific tool). In Claude Code use the `Agent` tool instead — pass `subagent_type: "general-purpose"` for implementer/reviewer/fixer roles, `prompt` for the full task+context text, and optionally `isolation: "worktree"` when parallel agents would touch the same files. There is no `toolsets` parameter — a general-purpose agent has full tool access already.

## When to Use

Use this skill when:
- You have an implementation plan (from writing-plans skill or user requirements)
- Tasks are mostly independent
- Quality and spec compliance are important
- You want automated review between tasks

**vs. manual execution:**
- Fresh context per task (no confusion from accumulated state)
- Automated review process catches issues early
- Consistent quality checks across all tasks
- Subagents can ask questions before starting work

## The Process

### 1. Read and Parse Plan

Read the plan file. Extract ALL tasks with their full text and context upfront. Create a todo list:

```python
# Read the plan
read_file("docs/plans/feature-plan.md")

# Create todo list with all tasks
todo([
    {"id": "task-1", "content": "Create User model with email field", "status": "pending"},
    {"id": "task-2", "content": "Add password hashing utility", "status": "pending"},
    {"id": "task-3", "content": "Create login endpoint", "status": "pending"},
])
```

**Key:** Read the plan ONCE. Extract everything. Don't make subagents read the plan file — provide the full task text directly in context.

### 2. Per-Task Workflow

For EACH task in the plan:

#### Step 1: Dispatch Implementer Subagent

Use the `Agent` tool with complete context in the prompt:

```
Agent({
  subagent_type: "general-purpose",
  description: "Implement User model task",
  prompt: `Implement Task 1: Create User model with email and password_hash fields.

TASK FROM PLAN:
- Create: src/models/user.py
- Add User class with email (str) and password_hash (str) fields
- Use bcrypt for password hashing
- Include __repr__ for debugging

FOLLOW TDD:
1. Write failing test in tests/models/test_user.py
2. Run: pytest tests/models/test_user.py -v (verify FAIL)
3. Write minimal implementation
4. Run: pytest tests/models/test_user.py -v (verify PASS)
5. Run: pytest tests/ -q (verify no regressions)
6. Commit: git add -A && git commit -m "feat: add User model with password hashing"

PROJECT CONTEXT:
- Python 3.11, Flask app in src/app.py
- Existing models in src/models/
- Tests use pytest, run from project root
- bcrypt already in requirements.txt`
})
```

#### Step 2: Dispatch Spec Compliance Reviewer

After the implementer completes, verify against the original spec:

```
Agent({
  subagent_type: "general-purpose",
  description: "Spec compliance review",
  prompt: `Review if this implementation matches the spec from the plan.

ORIGINAL TASK SPEC:
- Create src/models/user.py with User class
- Fields: email (str), password_hash (str)
- Use bcrypt for password hashing
- Include __repr__

CHECK:
- [ ] All requirements from spec implemented?
- [ ] File paths match spec?
- [ ] Function signatures match spec?
- [ ] Behavior matches expected?
- [ ] Nothing extra added (no scope creep)?

OUTPUT: PASS or list of specific spec gaps to fix.`
})
```

**If spec issues found:** Fix gaps, then re-run spec review. Continue only when spec-compliant.

#### Step 3: Dispatch Code Quality Reviewer

After spec compliance passes:

```
Agent({
  subagent_type: "general-purpose",
  description: "Code quality review",
  prompt: `Review code quality for Task 1 implementation.

FILES TO REVIEW:
- src/models/user.py
- tests/models/test_user.py

CHECK:
- [ ] Follows project conventions and style?
- [ ] Proper error handling?
- [ ] Clear variable/function names?
- [ ] Adequate test coverage?
- [ ] No obvious bugs or missed edge cases?
- [ ] No security issues?

OUTPUT FORMAT:
- Critical Issues: [must fix before proceeding]
- Important Issues: [should fix]
- Minor Issues: [optional]
- Verdict: APPROVED or REQUEST_CHANGES`
})
```

**If quality issues found:** Fix issues, re-review. Continue only when approved.

#### Step 4: Mark Complete

```python
todo([{"id": "task-1", "content": "Create User model with email field", "status": "completed"}], merge=True)
```

### 3. Final Review

After ALL tasks are complete, dispatch a final integration reviewer:

```
Agent({
  subagent_type: "general-purpose",
  description: "Final integration review",
  prompt: `Review the entire implementation for consistency and integration issues.

All tasks from the plan are complete. Review the full implementation:
- Do all components work together?
- Any inconsistencies between tasks?
- All tests passing?
- Ready for merge?`
})
```

### 4. Verify and Commit

```bash
# Run full test suite
pytest tests/ -q

# Review all changes
git diff --stat

# Final commit if needed
git add -A && git commit -m "feat: complete [feature name] implementation"
```

## Task Granularity

**Each task = 2-5 minutes of focused work.**

**Too big:**
- "Implement user authentication system"

**Right size:**
- "Create User model with email and password fields"
- "Add password hashing function"
- "Create login endpoint"
- "Add JWT token generation"
- "Create registration endpoint"

## Red Flags — Never Do These

- Start implementation without a plan
- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed critical/important issues
- Dispatch multiple implementation subagents for tasks that touch the same files
- Make subagent read the plan file (provide full text in context instead)
- Skip scene-setting context (subagent needs to understand where the task fits)
- Ignore subagent questions (answer before letting them proceed)
- Accept "close enough" on spec compliance
- Skip review loops (reviewer found issues → implementer fixes → review again)
- Let implementer self-review replace actual review (both are needed)
- **Start code quality review before spec compliance is PASS** (wrong order)
- Move to next task while either review has open issues

## Handling Issues

### If Subagent Asks Questions

- Answer clearly and completely
- Provide additional context if needed
- Don't rush them into implementation

### If Reviewer Finds Issues

- Implementer subagent (or a new one) fixes them
- Reviewer reviews again
- Repeat until approved
- Don't skip the re-review

### If Subagent Fails a Task

- Dispatch a new fix subagent with specific instructions about what went wrong
- Don't try to fix manually in the controller session (context pollution)

### Scope Too Large — Commit Per Phase

If the plan has multiple phases or the user says "todo tiene que estar listo", warn the user FIRST before delegating. Large multi-phase plans get interrupted mid-context and nothing gets done.

Instead: break into separate delegation calls, each with its own commit:
```
Phase 1 → delegate → commit → verify
Phase 2 → delegate → commit → verify
Phase 3 → delegate → commit → verify
```

Each delegation call is a fresh context — no shared state between phases.

**Red flag phrases** that mean "scope too large": "todo esté listo", "overhaul", "complete refactor of X", "3 pasos sin romper nada". When you hear these, break it down and present the sequence to the user first.

**If a subagent IS interrupted**: the work is lost unless the subagent committed before the interrupt. Always tell subagents to `git commit` after each completed phase.

## Efficiency Notes

**Why fresh subagent per task:**
- Prevents context pollution from accumulated state
- Each subagent gets clean, focused context
- No confusion from prior tasks' code or reasoning

**Why two-stage review:**
- Spec review catches under/over-building early
- Quality review ensures the implementation is well-built
- Catches issues before they compound across tasks

**Cost trade-off:**
- More subagent invocations (implementer + 2 reviewers per task)
- But catches issues early (cheaper than debugging compounded problems later)

### Delegación de tareas grandes (comprobado)

Este patrón ha funcionado exitosamente para tareas grandes (500+ líneas, 20+ tool calls):

- **Deep checks scanner**: 1,366 líneas deep-checks.ts, 28 tool calls, ~500s → ✅ exitoso
- **Full redesign landing page**: 15 archivos, 247s → ✅ exitoso
- **Metrix SEO multi-phase build**: 6 fases, Django + Scrapy + SF CLI + Next.js, 66 backend tests OK, frontend type-check OK → ✅ exitoso

La clave es dar contexto completo en el prompt de delegación: paths exactos, patrón del proyecto, restricciones específicas, y comando de verificación (build/test).

## Parallel Subagent Execution

### When to parallelize

Run implementer subagents in parallel when:
- Tasks are independent (no shared files)
- Each task has a clear, isolated scope
- You can enforce strict "no touching other files" rules
- The user explicitly asks for maximum parallelism

### Anti-pattern: shared-file races

If multiple subagents can write the same file, you will get race conditions:
- `spiders/tests.py` overwritten by competing agents
- `settings.py` patched simultaneously by different tasks
- `migrations/0002_*.py` duplicated or deleted

### How to parallelize safely

1. **Partition by directory/file ownership**
   - Task A owns only `spiders/scrapy/` and `spiders/tasks.py`
   - Task B owns only `audits/services/` and `audits/tasks.py`
   - Neither task touches shared files like `settings.py` or `models.py`

2. **Front-load shared infrastructure**
   - Commit the base layer (models, settings, URLs) BEFORE dispatching parallel tasks
   - Parallel tasks read but never modify the shared layer

3. **Use strict rules in the delegation prompt**
   ```
   REGLAS ESTRICTAS (violación = fallo):
   - NO modifiques NUNCA settings.py, spiders/models.py, audits/models.py
   - Puedes modificar SOLO: spiders/scrapy/*, spiders/tasks.py, spiders/tests.py
   - Si encuentras que un archivo necesario no existe, reporta y detente; no lo crees tú
   ```

4. **Single-writer per file**
   - If two tasks need the same file, serialize them or assign the file to one task only
   - Tests are a common collision point: give each task its own test file or merge tests in the parent after subagents finish

5. **Check git status before commit**
   - If a subagent says "another subagent deleted my files", verify with `git status`
   - Re-create missing files in the parent if needed, or re-run the subagent with stricter rules

### When subagents hit max_iterations

Subagents may terminate with `exit_reason: max_iterations` after completing work but before committing. In that case:
- Read the subagent summary to identify what was done
- Verify the changes in the parent session
- Run the verification command yourself
- Make the commit with the correct git identity

Do NOT assume a subagent committed just because it said tests pass.

### Parallelism + large frontends

When delegating a Next.js frontend alongside a backend:
- The backend API should be committed first so the frontend can reference real endpoints
- Do not run `npm run build` on low-RAM VPSs; use `npx tsc --noEmit` as the validation gate
- The frontend task can run in parallel with backend tasks only if it does not depend on unfinished backend endpoints

## Integration with Other Skills

### With writing-plans

This skill EXECUTES plans created by the writing-plans skill:
1. User requirements → writing-plans → implementation plan
2. Implementation plan → subagent-driven-development → working code

### With test-driven-development

Implementer subagents should follow TDD:
1. Write failing test first
2. Implement minimal code
3. Verify test passes
4. Commit

Include TDD instructions in every implementer context.

### With requesting-code-review

The two-stage review process IS the code review. For final integration review, use the requesting-code-review skill's review dimensions.

### With systematic-debugging

If a subagent encounters bugs during implementation:
1. Follow systematic-debugging process
2. Find root cause before fixing
3. Write regression test
4. Resume implementation

## Example Workflow

```
[Read plan: docs/plans/auth-feature.md]
[Create todo list with 5 tasks]

--- Task 1: Create User model ---
[Dispatch implementer subagent]
  Implementer: "Should email be unique?"
  You: "Yes, email must be unique"
  Implementer: Implemented, 3/3 tests passing, committed.

[Dispatch spec reviewer]
  Spec reviewer: ✅ PASS — all requirements met

[Dispatch quality reviewer]
  Quality reviewer: ✅ APPROVED — clean code, good tests

[Mark Task 1 complete]

--- Task 2: Password hashing ---
[Dispatch implementer subagent]
  Implementer: No questions, implemented, 5/5 tests passing.

[Dispatch spec reviewer]
  Spec reviewer: ❌ Missing: password strength validation (spec says "min 8 chars")

[Implementer fixes]
  Implementer: Added validation, 7/7 tests passing.

[Dispatch spec reviewer again]
  Spec reviewer: ✅ PASS

[Dispatch quality reviewer]
  Quality reviewer: Important: Magic number 8, extract to constant
  Implementer: Extracted MIN_PASSWORD_LENGTH constant
  Quality reviewer: ✅ APPROVED

[Mark Task 2 complete]

... (continue for all tasks)

[After all tasks: dispatch final integration reviewer]
[Run full test suite: all passing]
[Done!]
```

## Remember

```
Fresh subagent per task
Two-stage review every time
Spec compliance FIRST
Code quality SECOND
Never skip reviews
Catch issues early
```

**Quality is not an accident. It's the result of systematic process.**
