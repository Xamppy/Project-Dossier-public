# Parallel Delegation Prompt Template

Use this template when dispatching multiple `Agent` tool subagents in parallel for independent implementation phases.

## Why this shape

The template minimizes shared-file races by:
- Explicitly listing allowed and forbidden files
- Requiring a single verification command
- Banning modifications to shared infrastructure (settings, base models, migrations already committed)
- Forcing the subagent to report rather than create missing dependencies

## Template

```
Agent({
  subagent_type: "general-purpose",
  description: "Implement [PHASE_NAME]",
  isolation: "worktree",   // only if parallel agents could touch the same files
  prompt: `Implement [PHASE_NAME] in [PROJECT_PATH].

## Context

Project [PROJECT_PATH], branch [BRANCH]. [PHASE_PREVIOUS] already committed and verified.

Models/services available:
- [Model A]
- [Model B]
- [API endpoints if already exist]

## Task

Implement [PHASE_NAME] by reading docs/exec-plans/active/[PLAN].md COMPLETELY.

## STRICT RULES (violation = failure)

1. NEVER modify these files: settings.py, [model_file_1].py, [model_file_2].py, [tests_shared].py, [urls].py
2. You may modify ONLY: [allowed files]
3. Create directories [X], [Y] if they do not exist.
4. NEVER hardcode credentials, proxies, user agents, or absolute CLI paths.
5. Follow TDD: write tests first, then code, then run tests.
6. Maximum [N] concurrent requests / delay [D]s for spiders.
7. Mock external binaries (e.g., Screaming Frog CLI) in tests.
8. Use the git identity already configured in the repo — do not override user.name/user.email.
9. Atomic commit: [type]([TICKET]): [description]

## Final verification

cd [PROJECT_PATH]
source .venv/bin/activate
python manage.py check
python manage.py test [app]

## Output

Report files changed, test results, and commit hash.`
})
```

## Post-parallel checklist for the parent

1. Run `git status` to detect deleted/overwritten files.
2. Run the full test suite to catch integration issues.
3. If a subagent exited with `max_iterations`, verify its work and commit manually.
4. Move Trello/jira cards before dispatching the next wave.

## Example: splitting a Django + Next.js project

Wave 1 (sequential, shared infrastructure):
- SEO-001: Django models + settings + security

Wave 2 (parallel, file-disjoint):
- SEO-002: Scrapy spiders + Celery (owns `spiders/scrapy/`, `spiders/tasks.py`)
- SEO-003: Screaming Frog wrapper (owns `audits/services/`, `audits/tasks.py`)

Wave 3 (sequential, depends on Wave 2):
- SEO-004: DRF API endpoints

Wave 4 (sequential, depends on Wave 3):
- SEO-005: Next.js dashboard
