"""Agent subprocess that manages project memory skills."""

import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import tiktoken
from claude_agent_sdk import query, ClaudeAgentOptions

LOG_PATH = Path.home() / ".config" / "skills" / "agent.log"

AGENT_PROMPT = '''You are responsible for maintaining the persistent memory for this project as Claude Code skills.

## Skills Directory Structure

Skills live in `.claude/skills/<skill-name>/` with the following structure:

```
.claude/skills/
└── project-memory/
    ├── SKILL.md          # Required. Main skill file with YAML frontmatter + content
    ├── details.md        # Optional. Extended information referenced from SKILL.md
    └── <other>.md        # Optional. Additional files as needed
```

## File Format

**SKILL.md** (required, keep under 500 lines):
```yaml
---
name: project-memory
description: Persistent, evolving summary of project goals, progress, and key knowledge. Should be short and concise. Used by Claude to determine whether to load the skill or not.
---

# Project Memory

[Core project knowledge here]
```

**Supporting files** (optional, loaded only when referenced):
- Use for detailed information that doesn't need to be in every conversation
- Keep each file focused on a specific area
- Reference from SKILL.md so Claude knows they exist

## How Skills Are Used

The main Claude Code agent:
- Loads skill names and descriptions at startup
- Automatically activates relevant skills based on conversation context
- Reads the full SKILL.md content when activated
- Reads referenced files only when needed

## Current Context

{transcript_window}

## Existing Skills

{skill_tree}

## Guidelines

- Every project with a meaningful purpose should have a generic `project-memory` skill, which contains the key goals, essential knowledge, progress, and other important information relevant to this project that should be remembered across sessions.
- Summarise and refine the skill as needed, using your best judgement to decide how to manage the skills.
- If significant subprojects emerge within the current project, it is ok to create separate `<subproject>-memory` skills, but they should be created only as needed.
- Work only from the context provided above. Do not explore the codebase.

## Instructions

1. Decide what changes (if any) are needed to the skills based on the conversation context.
2. If changes are needed, USE THE WRITE OR EDIT TOOL to actually create/modify the skill files. Do not just describe what you would do - actually do it.
3. After making changes (or deciding none are needed), output a brief summary (e.g., "Created project-memory skill" or "Updated goals section" or "No changes needed").

IMPORTANT: You must use the Write tool to create or edit the skills files.
'''


def log(message: str) -> None:
    """Log a message to the agent log file."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    with open(LOG_PATH, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def kill_child_processes() -> None:
    """Kill all child processes of this process."""
    import subprocess
    pid = os.getpid()
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
        )
        child_pids = result.stdout.strip().split("\n")
        for child_pid in child_pids:
            if child_pid:
                try:
                    os.kill(int(child_pid), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
    except Exception:
        pass


class Agent:
    """Agent that manages project memory skills."""

    def __init__(self, context: dict):
        self.context = context
        self.cwd = Path(context.get("cwd", "."))
        self.transcript_window = context.get("transcript_window", [])
        self.parent_pid = os.getppid()
        self.running = True
        self.encoder = tiktoken.get_encoding("cl100k_base")

    @property
    def skills_dir(self) -> Path:
        return self.cwd / ".claude" / "skills"

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoder.encode(text))

    def _list_skills(self) -> dict[str, list[str]]:
        """List all skills and their files."""
        skills = {}
        if not self.skills_dir.exists():
            return skills

        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                files = [f.name for f in skill_dir.iterdir() if f.is_file()]
                skills[skill_dir.name] = files
        return skills

    def _get_skill_tree(self) -> str:
        """Get a formatted tree of existing skills."""
        skills = self._list_skills()
        if not skills:
            return "(no skills found)"

        lines = []
        for skill_name, files in sorted(skills.items()):
            lines.append(f"- {skill_name}/")
            for f in sorted(files):
                lines.append(f"    - {f}")
        return "\n".join(lines)

    def _read_existing_skills(self) -> str:
        """Read content of existing skill files."""
        if not self.skills_dir.exists():
            return "(no skills)"

        content_parts = []
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    content_parts.append(f"### {skill_dir.name}/SKILL.md\n```\n{skill_md.read_text()}\n```")

        return "\n\n".join(content_parts) if content_parts else "(no skills)"

    def _format_transcript_window(self) -> str:
        """Format transcript window for the prompt."""
        if not self.transcript_window:
            return "(no conversation context)"

        lines = []
        for msg in self.transcript_window:
            msg_type = msg.get("type", "unknown")
            if msg_type == "human":
                content = msg.get("message", {}).get("content", "")
                lines.append(f"USER: {content[:500]}")
            elif msg_type == "assistant":
                content = msg.get("message", {}).get("content", [])
                if isinstance(content, list):
                    text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                    text = " ".join(text_parts)
                else:
                    text = str(content)
                lines.append(f"ASSISTANT: {text[:500]}")
        return "\n\n".join(lines) if lines else "(no conversation context)"

    async def _monitor_parent(self) -> None:
        """Monitor parent process, exit if orphaned.

        NOTE: Disabled for now - was causing premature exits on SessionEnd.
        The overseer awaits the agent, so orphan detection isn't needed.
        """
        # Just sleep forever - the agent will complete naturally
        while self.running:
            await asyncio.sleep(10)

    async def process(self) -> str:
        """Process context and manage skills with Claude Agent SDK."""
        transcript_text = self._format_transcript_window()
        skill_tree = self._get_skill_tree()
        existing_skills = self._read_existing_skills()

        prompt = AGENT_PROMPT.format(
            transcript_window=transcript_text,
            skill_tree=skill_tree,
        )

        # Add existing skill content so agent can edit without reading
        prompt += f"\n\n## Existing Skill Content\n\n{existing_skills}"

        prompt_tokens = self._count_tokens(prompt)
        log(f"starting: prompt_tokens={prompt_tokens}, transcript_msgs={len(self.transcript_window)}")

        options = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            cwd=str(self.cwd),
            allowed_tools=["Write", "Edit"],
        )

        start_time = time.time()
        result = []
        final_text = ""
        async for message in query(prompt=prompt, options=options):
            if not self.running:
                break
            result.append(str(message))
            # Extract text content from AssistantMessage objects
            if hasattr(message, 'content'):
                for block in message.content:
                    if hasattr(block, 'text'):
                        final_text = block.text  # Keep last text block as summary

        elapsed = time.time() - start_time
        output = "\n".join(result)
        output_tokens = self._count_tokens(output)

        log(f"finished: elapsed={elapsed:.1f}s, output_tokens={output_tokens}")
        log(f"final_text: {final_text if final_text else '(no text)'}")

        return final_text if final_text else output

    async def run(self) -> str:
        """Run agent with parent monitoring."""
        monitor_parent = asyncio.create_task(self._monitor_parent())

        try:
            result = await self.process()
            return result
        except Exception as e:
            log(f"error: {e}")
            raise
        finally:
            self.running = False
            kill_child_processes()
            monitor_parent.cancel()
            try:
                await monitor_parent
            except asyncio.CancelledError:
                pass


def main() -> None:
    """Entry point when run as subprocess."""
    data = sys.stdin.read()
    context = json.loads(data)

    agent = Agent(context)
    try:
        result = asyncio.run(agent.run())
        print(result)
    finally:
        kill_child_processes()


if __name__ == "__main__":
    main()
