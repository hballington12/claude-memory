---
name: project-memory
description: Persistent memory for the skills project - auto-generates Claude Code skills from conversation transcripts
---

# Project Memory

## Project Purpose

Auto-generate and maintain "skills" (persistent memory files) for Claude Code by monitoring conversation transcripts. Skills help Claude remember important project context across sessions.

## Architecture

### Core Components

1. **CLI** (`cli.py`) - Entry point with subcommands:
   - `skills init` - Sets up Claude Code hooks (SessionStart, UserPromptSubmit, Stop, SessionEnd)
   - `skills config` - Manage trigger thresholds (tokens vs prompts mode)
   - `skills daemon` - Start/notify the background overseer

2. **Hook System** - Integrates with Claude Code lifecycle:
   - Monitors conversation transcripts
   - Triggers skill updates based on thresholds
   - Launches background overseer process

3. **Overseer** - Background process that:
   - Analyzes conversation context
   - Decides what skill changes are needed
   - Creates/updates skill files in `.claude/skills/`

### Skill Structure

Skills live in `.claude/skills/<skill-name>/`:
- `SKILL.md` (required, <500 lines) - Main skill with YAML frontmatter
- Supporting `.md` files (optional) - Extended details

## Current State

- Project structure established
- Core CLI and hook system implemented
- Overseer process manages skill updates
- Skills auto-generated from conversation context
- **Ready for deployment** - Initial implementation complete

### Git Status
- All project files are untracked (no initial commit made yet)
- No remote repository configured
- **Next steps for deployment:**
  1. Make initial commit with all project files
  2. Create remote repo (GitHub/GitLab/etc.) and push
  3. Then can deploy to another machine

## Known Issues & Findings

### Skill Loading & Refresh Behavior

**Discovery:** Skills don't refresh mid-session once loaded.

- **At session start:** Claude loads skill names, descriptions, and can activate relevant skills
- **When activated:** Full SKILL.md content is loaded as a static snapshot
- **After edits:** Changes to skill files are NOT visible until:
  1. Reading the file directly with Read tool
  2. Starting a fresh session (most reliable)
  3. Re-invoking the skill (effectiveness unclear)

**Implications:**
- Newly created skills won't appear in available skills list until session restart
- Skill content updates won't be visible to Claude mid-session
- The overseer process creates/updates skills that become available in the *next* session

## Key Guidelines

- Every meaningful project should have a `project-memory` skill
- Keep skills concise and focused
- Create separate subproject skills only when needed
- Skills are automatically activated based on conversation relevance

## Maintenance Process

This skill is maintained by Claude Code itself through:
1. **Context Analysis** - Reviewing conversation transcripts for key information
2. **Intelligent Updates** - Adding new findings, goals, or architectural changes
3. **Refinement** - Summarizing and condensing information to stay under 500 lines
4. **Practical Changes** - Actually editing files using Write/Edit tools, not just describing changes

The overseer process uses the same guidelines to maintain other project skills.
