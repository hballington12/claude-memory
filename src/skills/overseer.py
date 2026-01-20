"""Overseer daemon that monitors Claude Code sessions."""

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import tiktoken


class Overseer:
    """Daemon that listens for hook events and spawns agents."""

    PID_FILE = Path("/tmp/skills_overseer.pid")
    SOCKET_PATH = Path("/tmp/skills_overseer.sock")
    CONFIG_PATH = Path.home() / ".config" / "skills" / "config.json"
    LOG_PATH = Path.home() / ".config" / "skills" / "overseer.log"

    DEFAULT_CONFIG = {
        "trigger_mode": "tokens",
        "token_threshold": 10000,
        "prompt_threshold": 5,
        "trigger_on_first_response": True,
    }

    def __init__(self):
        self.running = False
        self.session_id: str | None = None
        self.transcript_path: Path | None = None
        self.cwd: Path | None = None
        self.active_agent: subprocess.Popen | None = None

        # Trigger tracking
        self.prompt_count = 0
        self.response_count = 0
        self.tokens_since_last_trigger = 0
        self.last_transcript_length = 0

        # Load config
        self.config = self._load_config()

        # Token encoder for Claude models
        self.encoder = tiktoken.get_encoding("cl100k_base")

    def _load_config(self) -> dict:
        """Load config or return defaults."""
        if self.CONFIG_PATH.exists():
            with open(self.CONFIG_PATH) as f:
                config = json.load(f)
                return {**self.DEFAULT_CONFIG, **config}
        return self.DEFAULT_CONFIG.copy()

    def _log(self, message: str) -> None:
        """Log a message to the shared log file."""
        from datetime import datetime
        # Use same log as agent for consistency
        log_path = Path.home() / ".config" / "skills" / "agent.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat()
        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] overseer: {message}\n")

    @classmethod
    def is_running(cls) -> bool:
        """Check if the overseer is already running."""
        if not cls.PID_FILE.exists():
            return False

        try:
            pid = int(cls.PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, ValueError, FileNotFoundError):
            cls._cleanup_stale()
            return False

    @classmethod
    def _cleanup_stale(cls) -> None:
        """Clean up stale PID file and socket from crashed overseer."""
        cls.PID_FILE.unlink(missing_ok=True)
        cls.SOCKET_PATH.unlink(missing_ok=True)

    @classmethod
    def get_pid(cls) -> int | None:
        """Get the PID of the running overseer."""
        if not cls.PID_FILE.exists():
            return None
        return int(cls.PID_FILE.read_text().strip())

    def _write_pid(self) -> None:
        """Write current PID to file."""
        self.PID_FILE.write_text(str(os.getpid()))

    def _cleanup(self) -> None:
        """Clean up PID file, socket, and any active agent."""
        if self.active_agent and self.active_agent.poll() is None:
            self.active_agent.terminate()
            try:
                self.active_agent.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.active_agent.kill()

        self.PID_FILE.unlink(missing_ok=True)
        self.SOCKET_PATH.unlink(missing_ok=True)

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken."""
        return len(self.encoder.encode(text))

    def _read_transcript(self) -> list[dict]:
        """Read all messages from the transcript."""
        if not self.transcript_path:
            self._log("transcript: no path set")
            return []
        if not self.transcript_path.exists():
            self._log(f"transcript: path doesn't exist: {self.transcript_path}")
            return []

        messages = []
        with open(self.transcript_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return messages

    def _read_transcript_window(self, max_messages: int = 50) -> list[dict]:
        """Read the most recent messages from the transcript."""
        messages = self._read_transcript()
        return messages[-max_messages:]

    def _calculate_new_tokens(self) -> int:
        """Calculate tokens added since last check."""
        messages = self._read_transcript()
        current_length = len(messages)

        if current_length <= self.last_transcript_length:
            self._log(f"token_calc: no new msgs (current={current_length}, last={self.last_transcript_length})")
            return 0

        new_messages = messages[self.last_transcript_length:]
        self._log(f"token_calc: {len(new_messages)} new msgs (transcript has {current_length} total)")
        self.last_transcript_length = current_length

        total_tokens = 0
        for msg in new_messages:
            msg_type = msg.get("type", "")
            if msg_type == "human":
                content = msg.get("message", {}).get("content", "")
                total_tokens += self._count_tokens(str(content))
            elif msg_type == "assistant":
                content = msg.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for c in content:
                        if c.get("type") == "text":
                            total_tokens += self._count_tokens(c.get("text", ""))
                else:
                    total_tokens += self._count_tokens(str(content))

        return total_tokens

    def _build_agent_context(self) -> dict:
        """Build context dict to pass to agent subprocess."""
        return {
            "cwd": str(self.cwd) if self.cwd else ".",
            "session_id": self.session_id,
            "transcript_window": self._read_transcript_window(),
        }

    async def _spawn_agent(self) -> str | None:
        """Spawn agent subprocess with context via stdin."""
        context = self._build_agent_context()

        try:
            self.active_agent = subprocess.Popen(
                [sys.executable, "-m", "skills.agent"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.active_agent.stdin.write(json.dumps(context).encode())
            self.active_agent.stdin.flush()
            self.active_agent.stdin.close()

            loop = asyncio.get_event_loop()
            stdout, stderr = await loop.run_in_executor(
                None,
                lambda: self.active_agent.communicate(timeout=300),
            )

            # Reset trigger counters after agent run
            self.tokens_since_last_trigger = 0
            self.prompt_count = 0

            self._log(f"agent returncode: {self.active_agent.returncode}")

            if self.active_agent.returncode == 0:
                output = stdout.decode().strip()
                self._log(f"agent stdout ({len(output)} chars): {output[:1000] if output else '(empty)'}")
                return output
            else:
                stderr_text = stderr.decode().strip()
                self._log(f"agent failed (rc={self.active_agent.returncode}): {stderr_text[:500]}")
                return None

        except subprocess.TimeoutExpired:
            if self.active_agent:
                self.active_agent.kill()
            return None
        except Exception:
            return None
        finally:
            self.active_agent = None

    def _should_trigger_agent(self, event_name: str) -> bool:
        """Decide if we should trigger the agent based on config and conditions."""
        # Trigger on first response if configured
        if self.config["trigger_on_first_response"]:
            if event_name == "Stop" and self.response_count == 1:
                self._log("trigger: first_response")
                return True

        # Check based on trigger mode
        if self.config["trigger_mode"] == "tokens":
            should = self.tokens_since_last_trigger >= self.config["token_threshold"]
            if should:
                self._log(f"trigger: token_threshold ({self.tokens_since_last_trigger} >= {self.config['token_threshold']})")
            return should
        else:  # prompts mode
            should = self.prompt_count >= self.config["prompt_threshold"]
            if should:
                self._log(f"trigger: prompt_threshold ({self.prompt_count} >= {self.config['prompt_threshold']})")
            return should

    async def run(self) -> None:
        """Run the overseer loop."""
        self.running = True
        self._write_pid()

        def handle_signal(sig, frame):
            self.running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        self.SOCKET_PATH.unlink(missing_ok=True)

        server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.SOCKET_PATH),
        )

        async with server:
            while self.running:
                await asyncio.sleep(0.1)

        self._cleanup()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle incoming hook events."""
        data = await reader.read(65536)
        message = data.decode()

        try:
            event = json.loads(message)
            await self._process_event(event)
            response = "ok"
        except Exception as e:
            response = f"error: {e}"

        writer.write(response.encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _process_event(self, event: dict) -> None:
        """Process a hook event."""
        event_name = event.get("hook_event_name", "")
        self.session_id = event.get("session_id")

        if "transcript_path" in event:
            self.transcript_path = Path(event["transcript_path"])

        if "cwd" in event:
            self.cwd = Path(event["cwd"])

        # Calculate new tokens from transcript
        new_tokens = self._calculate_new_tokens()
        self.tokens_since_last_trigger += new_tokens

        self._log(f"event={event_name} new_tokens={new_tokens} total_tokens={self.tokens_since_last_trigger} prompts={self.prompt_count} responses={self.response_count}")

        if event_name == "SessionEnd":
            # Trigger agent one final time before shutdown
            await self._spawn_agent()
            self.running = False

        elif event_name == "UserPromptSubmit":
            self.prompt_count += 1

        elif event_name == "Stop":
            # Claude finished responding
            self.response_count += 1

            if self._should_trigger_agent(event_name):
                await self._spawn_agent()

    @classmethod
    async def send_event(cls, event: dict) -> str | None:
        """Send an event to the running overseer."""
        if not cls.is_running():
            return None

        try:
            reader, writer = await asyncio.open_unix_connection(str(cls.SOCKET_PATH))
            writer.write(json.dumps(event).encode())
            await writer.drain()
            writer.write_eof()

            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            return response.decode()
        except (ConnectionRefusedError, FileNotFoundError):
            return None
