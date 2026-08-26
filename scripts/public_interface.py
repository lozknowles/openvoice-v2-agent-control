#!/usr/bin/env python3
"""Bounded, CPU-only OpenVoice UI for the password-protected public beta."""

import argparse
import hashlib
import os
import secrets
import shutil
import threading
import time
from pathlib import Path

if __package__:
    from .openvoice_v2_runtime import (
        ALLOWED_REFERENCE_SUFFIXES,
        OpenVoiceV2Runtime,
        SUPPORTED_LANGUAGES,
        synthetic_output_name,
        validate_bind_host,
    )
    from .local_interface import select_reference
else:
    from openvoice_v2_runtime import (
        ALLOWED_REFERENCE_SUFFIXES,
        OpenVoiceV2Runtime,
        SUPPORTED_LANGUAGES,
        synthetic_output_name,
        validate_bind_host,
    )
    from local_interface import select_reference


PUBLIC_ROOT_PATH = "/voice-clone"
PUBLIC_MAX_REFERENCE_BYTES = 15 * 1024 * 1024
PUBLIC_MIN_REFERENCE_MS = 2_000
PUBLIC_MAX_REFERENCE_MS = 30_000
PUBLIC_MAX_TEXT_CHARS = 300
PUBLIC_RETENTION_SECONDS = 60 * 60
PUBLIC_GLOBAL_REQUESTS_PER_HOUR = 12
PUBLIC_CLIENT_REQUESTS_PER_HOUR = 4

CONSENT_NOTICE = """
### Consent required

Use **only your own voice**, or a voice for which you have explicit permission
from the speaker. Password access does not grant permission to clone somebody
else. Do not use this beta for impersonation, fraud, authentication bypass,
harassment or deception.

Every result is synthetic, uses an `_synthetic.wav` filename, and preserves the
upstream `@MyShell` watermark where audio length permits. References and outputs
are automatically removed from the server within one hour. Keep your downloaded
result labelled as synthetic.
"""


def _within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_public_text(text):
    value = str(text or "").strip()
    if len(value) < 2 or len(value) > PUBLIC_MAX_TEXT_CHARS:
        raise ValueError(
            "Text must be between 2 and %d characters" % PUBLIC_MAX_TEXT_CHARS
        )
    return value


def validate_public_reference(reference_path, upload_root):
    from pydub import AudioSegment

    root = Path(upload_root).resolve()
    reference = Path(reference_path).resolve()
    if not _within(reference, root):
        raise ValueError("Reference must come from this upload or microphone session")
    if not reference.is_file() or reference.suffix.lower() not in ALLOWED_REFERENCE_SUFFIXES:
        raise ValueError("Reference must be a WAV or MP3 file")
    if reference.stat().st_size > PUBLIC_MAX_REFERENCE_BYTES:
        raise ValueError("Reference exceeds the 15 MiB public beta limit")
    try:
        audio = AudioSegment.from_file(str(reference))
    except Exception as exc:
        raise ValueError("Reference could not be decoded as WAV or MP3") from exc
    if len(audio) < PUBLIC_MIN_REFERENCE_MS or len(audio) > PUBLIC_MAX_REFERENCE_MS:
        raise ValueError("Reference speech must be between 2 and 30 seconds")
    return reference


def client_identity(request):
    """Return an in-memory pseudonymous rate-limit key; never write it to disk."""

    headers = getattr(request, "headers", {}) or {}
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        peer = forwarded.rsplit(",", 1)[-1].strip()
    else:
        client = getattr(request, "client", None)
        peer = str(getattr(client, "host", "unknown"))
    return hashlib.sha256(peer.encode("utf-8", "replace")).hexdigest()[:24]


class FixedWindowLimiter:
    """Small in-process limiter protecting the CPU queue without retaining IPs."""

    def __init__(
        self,
        global_limit=PUBLIC_GLOBAL_REQUESTS_PER_HOUR,
        client_limit=PUBLIC_CLIENT_REQUESTS_PER_HOUR,
        window_seconds=60 * 60,
    ):
        self.global_limit = int(global_limit)
        self.client_limit = int(client_limit)
        self.window_seconds = int(window_seconds)
        self._lock = threading.Lock()
        self._global_events = []
        self._client_events = {}

    def consume(self, client_key, now=None):
        current = time.monotonic() if now is None else float(now)
        cutoff = current - self.window_seconds
        with self._lock:
            self._global_events = [value for value in self._global_events if value > cutoff]
            client_events = [
                value for value in self._client_events.get(client_key, []) if value > cutoff
            ]
            if len(self._global_events) >= self.global_limit:
                return False, "The shared beta has reached its hourly limit; please try later"
            if len(client_events) >= self.client_limit:
                return False, "This browser connection has reached its hourly limit"
            self._global_events.append(current)
            client_events.append(current)
            self._client_events[client_key] = client_events
        return True, ""


def remove_uploaded_reference(reference_path, upload_root):
    if not reference_path:
        return
    root = Path(upload_root).resolve()
    reference = Path(reference_path).resolve()
    if not _within(reference, root):
        return
    reference.unlink(missing_ok=True)
    parent = reference.parent
    while parent != root and _within(parent, root):
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def cleanup_expired(data_root, retention_seconds=PUBLIC_RETENTION_SECONDS, now=None):
    current = time.time() if now is None else float(now)
    removed = 0
    for folder_name in ("gradio", "outputs"):
        folder = Path(data_root) / folder_name
        if not folder.is_dir():
            continue
        for entry in tuple(folder.iterdir()):
            try:
                expired = current - entry.stat().st_mtime >= retention_seconds
            except FileNotFoundError:
                continue
            if not expired:
                continue
            if entry.is_dir():
                shutil.rmtree(str(entry), ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            removed += 1
    return removed


def start_cleanup_worker(data_root):
    def worker():
        while True:
            cleanup_expired(data_root)
            time.sleep(15 * 60)

    thread = threading.Thread(target=worker, name="openvoice-retention", daemon=True)
    thread.start()
    return thread


def prepare_data_root(value):
    runtime_root = Path(
        os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    ).resolve()
    expected = (runtime_root / "openvoice-v2-public").resolve()
    candidate = Path(value).resolve()
    if candidate != expected:
        raise ValueError("Public beta data must stay in the systemd runtime directory")
    for path in (candidate, candidate / "gradio", candidate / "outputs"):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    return candidate


def build_app(data_root, limiter=None):
    import gradio as gr

    data_root = Path(data_root).resolve()
    upload_root = data_root / "gradio"
    output_root = data_root / "outputs"
    limiter = limiter or FixedWindowLimiter()

    def generate(
        upload_reference,
        microphone_reference,
        text,
        language,
        output_filename,
        consent,
        request: gr.Request,
    ):
        reference = None
        try:
            if not consent:
                raise ValueError("Consent confirmation is required")
            reference = select_reference(upload_reference, microphone_reference)
            clean_text = validate_public_text(text)
            allowed, reason = limiter.consume(client_identity(request))
            if not allowed:
                raise ValueError(reason)
            reference = validate_public_reference(reference, upload_root)

            request_root = output_root / secrets.token_hex(12)
            request_root.mkdir(parents=True, mode=0o700)
            prefix = Path(synthetic_output_name(output_filename)).stem.replace(
                "_synthetic", ""
            )
            runtime = OpenVoiceV2Runtime(device="cpu", language=language)
            result = runtime.synthesise_many(
                reference_path=reference,
                texts=[clean_text],
                output_dir=request_root,
                filename_prefix=prefix,
                consent_confirmed=True,
                consent_basis=(
                    "password-beta user affirmed own voice or explicit speaker permission"
                ),
            )
            output = result["outputs"][0]
            output_path = request_root / output["filename"]
            status = (
                "Synthetic output ready. CPU generation %.1fs; audio %.1fs; "
                "real-time factor %.2f. The @MyShell watermark was requested. "
                "The server copy expires within one hour."
                % (
                    output["generation_seconds"],
                    output["signal"]["duration_seconds"],
                    output["real_time_factor"],
                )
            )
            return str(output_path), status
        except (PermissionError, ValueError) as exc:
            raise gr.Error(str(exc)) from exc
        except Exception as exc:
            raise gr.Error(
                "Generation could not complete. Try a shorter, clean single-speaker recording."
            ) from exc
        finally:
            remove_uploaded_reference(reference, upload_root)

    with gr.Blocks(title="Voice Clone — password beta") as app:
        gr.Markdown("# Voice Clone")
        gr.Markdown("Password-protected, CPU-only OpenVoice V2 experiment.")
        gr.Markdown(CONSENT_NOTICE)
        with gr.Row():
            with gr.Column():
                gr.Markdown("Choose exactly one authorised reference source.")
                with gr.Tabs():
                    with gr.Tab("Drop or upload"):
                        upload_reference = gr.Audio(
                            label="Authorised reference — WAV/MP3, 2–30 seconds",
                            type="filepath",
                            source="upload",
                            show_share_button=False,
                        )
                    with gr.Tab("Record microphone"):
                        microphone_reference = gr.Audio(
                            label="Authorised reference — record 2–30 seconds",
                            type="filepath",
                            source="microphone",
                            format="wav",
                            show_share_button=False,
                        )
            with gr.Column():
                text = gr.Textbox(
                    label="Text",
                    lines=5,
                    max_lines=8,
                )
                language = gr.Dropdown(
                    label="Language/accent",
                    choices=list(SUPPORTED_LANGUAGES.keys()),
                    value="British English",
                )
                output_filename = gr.Textbox(label="Output filename", value="voice-clone")
                consent = gr.Checkbox(
                    label="I confirm this is my voice or I have explicit permission",
                    value=False,
                )
                submit = gr.Button("Generate synthetic audio", variant="primary")
        output_audio = gr.Audio(label="Synthetic output", type="filepath")
        status = gr.Textbox(label="Generation status", interactive=False)
        submit.click(
            fn=generate,
            inputs=[
                upload_reference,
                microphone_reference,
                text,
                language,
                output_filename,
                consent,
            ],
            outputs=[output_audio, status],
            api_name=False,
        )
    app.queue(concurrency_count=1, max_size=2)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=17862)
    parser.add_argument("--root-path", default=PUBLIC_ROOT_PATH)
    parser.add_argument(
        "--data-root",
        default=os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()),
            "openvoice-v2-public",
        ),
    )
    args = parser.parse_args()
    host = validate_bind_host(args.host)
    if args.root_path.rstrip("/") != PUBLIC_ROOT_PATH:
        raise ValueError("The public beta root path is fixed at %s" % PUBLIC_ROOT_PATH)
    data_root = prepare_data_root(args.data_root)
    os.environ["GRADIO_TEMP_DIR"] = str(data_root / "gradio")
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    cleanup_expired(data_root)
    start_cleanup_worker(data_root)
    app = build_app(data_root)
    app.launch(
        server_name=host,
        server_port=args.port,
        root_path=PUBLIC_ROOT_PATH,
        share=False,
        show_error=False,
        show_api=False,
        inbrowser=False,
        quiet=True,
        max_threads=2,
        state_session_capacity=50,
        allowed_paths=[str(data_root)],
        blocked_paths=["/etc", "/fast", "/home", "/root", "/var"],
    )


if __name__ == "__main__":
    main()
