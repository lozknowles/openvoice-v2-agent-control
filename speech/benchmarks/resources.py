"""Bounded process, host-memory and NVIDIA measurements for benchmark calls."""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional


def gpu_state() -> Dict[str, Any]:
    result: Dict[str, Any] = {"available": False, "processes": []}
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,compute_cap,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        result["error"] = completed.stderr.strip() or "nvidia-smi unavailable"
        return result
    values = [value.strip() for value in completed.stdout.splitlines()[0].split(",")]
    if len(values) >= 7:
        result.update(
            {
                "available": True,
                "name": values[0],
                "driver": values[1],
                "compute_capability": values[2],
                "total_mib": int(values[3]),
                "used_mib": int(values[4]),
                "free_mib": int(values[5]),
                "utilization_percent": int(values[6]),
            }
        )
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        for line in completed.stdout.splitlines():
            fields = [value.strip() for value in line.split(",", 2)]
            if len(fields) == 3 and fields[0].isdigit():
                result["processes"].append(
                    {"pid": int(fields[0]), "name": fields[1], "used_mib": int(fields[2])}
                )
    return result


class ResourceMonitor:
    """Sample only; never changes priority, services, processes or GPU state."""

    def __init__(
        self,
        pid_supplier: Callable[[], Iterable[int]],
        interval_seconds: float = 0.25,
    ) -> None:
        self.pid_supplier = pid_supplier
        self.interval_seconds = interval_seconds
        self.samples: List[Dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._previous_cpu_seconds: Optional[float] = None
        self._previous_wall: Optional[float] = None

    @staticmethod
    def _process_snapshot(root_pids: Iterable[int]) -> Dict[str, Any]:
        try:
            import psutil
        except ImportError:
            return {"available": False, "error": "psutil unavailable"}
        processes = []
        seen = set()
        for pid in root_pids:
            try:
                root = psutil.Process(int(pid))
                candidates = [root] + root.children(recursive=True)
            except (psutil.Error, ValueError):
                continue
            for process in candidates:
                if process.pid in seen:
                    continue
                seen.add(process.pid)
                try:
                    memory = process.memory_info().rss
                    cpu = process.cpu_times()
                    processes.append(
                        {
                            "pid": process.pid,
                            "rss_bytes": memory,
                            "cpu_seconds": cpu.user + cpu.system,
                        }
                    )
                except psutil.Error:
                    continue
        virtual = psutil.virtual_memory()
        return {
            "available": True,
            "processes": processes,
            "rss_bytes": sum(item["rss_bytes"] for item in processes),
            "cpu_seconds": sum(item["cpu_seconds"] for item in processes),
            "host_cpu_percent": psutil.cpu_percent(interval=None),
            "host_memory_used_bytes": virtual.used,
            "host_memory_available_bytes": virtual.available,
        }

    def _sample(self) -> None:
        now = time.monotonic()
        process = self._process_snapshot(self.pid_supplier())
        cpu_percent = None
        if process.get("available"):
            cpu_seconds = float(process.get("cpu_seconds", 0.0))
            if self._previous_cpu_seconds is not None and self._previous_wall is not None:
                wall = max(now - self._previous_wall, 1e-9)
                cpu_percent = max(0.0, (cpu_seconds - self._previous_cpu_seconds) / wall * 100.0)
            self._previous_cpu_seconds = cpu_seconds
            self._previous_wall = now
        self.samples.append(
            {
                "monotonic": now,
                "process": process,
                "provider_cpu_percent": cpu_percent,
                "gpu": gpu_state(),
            }
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample()
            except Exception as exc:  # pragma: no cover - measurement must not stop synthesis
                self.samples.append(
                    {"monotonic": time.monotonic(), "measurement_error": type(exc).__name__}
                )
            self._stop.wait(self.interval_seconds)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        if not self.samples:
            self._sample()

    def summary(self) -> Dict[str, Any]:
        rss = []
        provider_cpu = []
        host_cpu = []
        host_used = []
        host_available = []
        gpu_total = []
        gpu_target = []
        target_pids = set(int(pid) for pid in self.pid_supplier())
        for sample in self.samples:
            process = sample.get("process") or {}
            if process.get("rss_bytes") is not None:
                rss.append(process["rss_bytes"])
            if sample.get("provider_cpu_percent") is not None:
                provider_cpu.append(sample["provider_cpu_percent"])
            if process.get("host_cpu_percent") is not None:
                host_cpu.append(process["host_cpu_percent"])
            if process.get("host_memory_used_bytes") is not None:
                host_used.append(process["host_memory_used_bytes"])
                host_available.append(process["host_memory_available_bytes"])
            gpu = sample.get("gpu") or {}
            if gpu.get("used_mib") is not None:
                gpu_total.append(gpu["used_mib"])
            for item in gpu.get("processes", []):
                if item.get("pid") in target_pids:
                    gpu_target.append(item.get("used_mib", 0))
        return {
            "sample_count": len(self.samples),
            "peak_provider_rss_bytes": max(rss) if rss else None,
            "peak_provider_cpu_percent": max(provider_cpu) if provider_cpu else None,
            "peak_host_cpu_percent": max(host_cpu) if host_cpu else None,
            "peak_host_memory_used_bytes": max(host_used) if host_used else None,
            "minimum_host_memory_available_bytes": min(host_available)
            if host_available
            else None,
            "peak_total_gpu_vram_mib": max(gpu_total) if gpu_total else None,
            "baseline_total_gpu_vram_mib": gpu_total[0] if gpu_total else None,
            "peak_new_total_gpu_vram_mib": (
                max(0, max(gpu_total) - gpu_total[0]) if gpu_total else None
            ),
            "peak_provider_gpu_vram_mib": max(gpu_target) if gpu_target else 0,
        }
