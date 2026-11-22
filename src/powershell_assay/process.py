"""Run literal commands with bounded POSIX process and output ownership."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time


@dataclass(frozen=True)
class Execution:
    exit_code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    unavailable: str | None = None

    def evidence(self):
        return {
            "exitCode": self.exit_code,
            "stdoutSha256": hashlib.sha256(self.stdout).hexdigest(),
            "stderrSha256": hashlib.sha256(self.stderr).hexdigest(),
            "collectedBytes": len(self.stdout) + len(self.stderr),
            "unavailable": self.unavailable,
        }


def run(argv: list[str], cwd: Path, *, source: bytes = b"",
        env: dict[str, str] | None = None, timeout: float = 30,
        output_limit: int = 1024 * 1024) -> Execution:
    if os.name != "posix":
        return Execution(unavailable="POSIX process runner required")

    with tempfile.TemporaryFile() as stdin:
        stdin.write(source)
        stdin.seek(0)
        try:
            child = subprocess.Popen(
                argv, cwd=cwd, stdin=stdin, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, start_new_session=True,
            )
        except OSError:
            return Execution(unavailable="executable could not start")

        streams = {"stdout": bytearray(), "stderr": bytearray()}
        reason = None
        deadline = time.monotonic() + timeout
        total = 0
        try:
            with child.stdout, child.stderr, selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ, "stdout")
                selector.register(child.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map() and reason is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        reason = "deadline exceeded"
                        break
                    for item, _ in selector.select(remaining):
                        chunk = os.read(item.fd, min(65536, output_limit - total + 1))
                        if not chunk:
                            selector.unregister(item.fileobj)
                            continue
                        streams[item.data].extend(chunk)
                        total += len(chunk)
                        if total > output_limit:
                            reason = "output limit exceeded"
                            break
            if reason is None:
                child.wait(timeout=max(0, deadline - time.monotonic()))
                if child.returncode < 0:
                    reason = "executable terminated by signal"
        except subprocess.TimeoutExpired:
            reason = "deadline exceeded"
        except OSError:
            reason = "output collection unavailable"
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                reason = "process cleanup unavailable"

        return Execution(child.returncode, bytes(streams["stdout"]), bytes(streams["stderr"]), reason)
