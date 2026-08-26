"""Provider contracts and the isolated JSON-line worker transport."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from speech.audio import probe_audio


class ProviderUnavailable(RuntimeError):
    """Raised when a configured provider cannot safely run."""


class ProviderAdapter(ABC):
    """Neutral provider contract. Provider-only controls stay behind adapters."""

    name: str
    engine: str

    @classmethod
    @abstractmethod
    def availability(cls) -> Tuple[bool, str]:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self):
        raise NotImplementedError

    @abstractmethod
    def synthesize(self, request, output_path: Path):
        raise NotImplementedError

    def process_ids(self) -> List[int]:
        return [os.getpid()]

    @property
    def initialization_seconds(self) -> Optional[float]:
        return None

    @property
    def initialization_metadata(self) -> Mapping[str, Any]:
        return {}

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class JsonWorkerProvider(ProviderAdapter):
    """Keep an engine in its own pinned environment while reusing loaded models."""

    startup_timeout_seconds = 180.0
    response_timeout_seconds = 900.0

    def __init__(self, command: Sequence[str], environment: Optional[Mapping[str, str]] = None):
        self._command = list(command)
        self._environment = dict(environment or {})
        self._process: Optional[subprocess.Popen] = None
        self._initialization_seconds: Optional[float] = None
        self._initialization_metadata: Dict[str, Any] = {}
        self._start_count = 0

    @staticmethod
    def _readline_with_timeout(stream, timeout: float) -> str:
        result: "queue.Queue[object]" = queue.Queue(maxsize=1)

        def read() -> None:
            try:
                result.put(stream.readline())
            except BaseException as exc:  # pragma: no cover - defensive transport boundary
                result.put(exc)

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        try:
            value = result.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("speech provider worker timed out") from exc
        if isinstance(value, BaseException):
            raise value
        return str(value)

    def _start(self) -> None:
        if self._process and self._process.poll() is None:
            return
        available, reason = self.availability()
        if not available:
            raise ProviderUnavailable(reason)
        environment = os.environ.copy()
        environment.update(self._environment)
        started = time.perf_counter()
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
            env=environment,
        )
        assert self._process.stdout is not None
        try:
            line = self._readline_with_timeout(
                self._process.stdout, self.startup_timeout_seconds
            )
            if not line:
                raise RuntimeError(
                    "speech provider worker exited during initialization (status %s)"
                    % self._process.poll()
                )
            payload = json.loads(line)
            if payload.get("type") != "ready" or not payload.get("ok"):
                raise RuntimeError(payload.get("error") or "invalid worker ready response")
            self._initialization_seconds = time.perf_counter() - started
            self._initialization_metadata = payload
            self._start_count += 1
        except Exception:
            self.close(force=True)
            raise

    @property
    def initialization_seconds(self) -> Optional[float]:
        self._start()
        return self._initialization_seconds

    @property
    def initialization_metadata(self) -> Mapping[str, Any]:
        self._start()
        return dict(self._initialization_metadata)

    def process_ids(self) -> List[int]:
        if self._process and self._process.poll() is None:
            return [self._process.pid]
        return []

    def worker_request(self, request, output_path: Path) -> Dict[str, Any]:
        return {
            "type": "synthesize",
            "text": request.text,
            "voice": request.voice,
            "speed": request.speed,
            "style": request.style,
            "output_format": request.output_format,
            "language": request.language,
            "output_path": str(output_path),
            "consent_confirmed": request.consent_confirmed,
            "consent_basis": request.consent_basis,
        }

    def synthesize(self, request, output_path: Path):
        from speech.interface import SynthesisResult

        started = time.perf_counter()
        self._start()
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        if output_path.exists():
            raise FileExistsError("refusing to overwrite existing audio: %s" % output_path)
        self._process.stdin.write(json.dumps(self.worker_request(request, output_path)) + "\n")
        self._process.stdin.flush()
        line = self._readline_with_timeout(
            self._process.stdout, self.response_timeout_seconds
        )
        total = time.perf_counter() - started
        if not line:
            raise RuntimeError("speech provider worker exited without a response")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "speech provider failed")
        response["worker_start_count"] = self._start_count
        actual_path = Path(response.get("output_path") or output_path).resolve()
        if actual_path != output_path.resolve():
            raise RuntimeError("speech worker returned an unexpected output path")
        audio = probe_audio(actual_path)
        duration = audio.get("duration_seconds")
        result = SynthesisResult(
            provider=self.name,
            engine=self.engine,
            output_path=actual_path,
            synthetic=True,
            time_to_first_audio_seconds=total,
            time_to_first_audio_kind="complete-file-availability",
            total_latency_seconds=total,
            real_time_factor=(total / duration) if duration else None,
            output_duration_seconds=duration,
            output_bytes=audio["bytes"],
            sample_rate=audio.get("sample_rate"),
            retries=int(response.get("retries", 0)),
            request_id=response.get("request_id"),
            estimated_cloud_cost_usd=None,
            metadata={
                "audio": audio,
                "worker": {k: v for k, v in response.items() if k not in {"ok"}},
            },
        )
        if response.get("recycle_after_response"):
            process = self._process
            self._process = None
            if process is not None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
        return result

    def close(self, force: bool = False) -> None:
        process = self._process
        self._process = None
        if not process or process.poll() is not None:
            return
        if not force and process.stdin is not None:
            try:
                process.stdin.write('{"type":"shutdown"}\n')
                process.stdin.flush()
                process.wait(timeout=10)
                return
            except (BrokenPipeError, subprocess.TimeoutExpired):
                pass
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
