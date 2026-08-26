#!/usr/bin/env python3
"""Local/Tailscale-only Gradio interface. There is deliberately no share mode."""

import argparse
import json

from openvoice_v2_runtime import (
    SUPPORTED_LANGUAGES,
    synthesise_one,
    validate_bind_host,
)


CONSENT_NOTICE = """
### Consent required

Upload only your own voice or a voice for which you have explicit permission.
Generated audio is synthetic, keeps the upstream `@MyShell` watermark where
audio length permits, and is written with `_synthetic.wav` plus metadata. Do not
use this tool for impersonation, fraud, authentication bypass or deception.
"""


def build_app(default_device):
    import gradio as gr

    def generate(reference, text, language, output_filename, device, consent):
        if not consent:
            raise gr.Error("Consent confirmation is required")
        if not reference:
            raise gr.Error("An authorised WAV or MP3 reference is required")
        output, metrics = synthesise_one(
            reference_path=reference,
            text=text,
            language=language,
            output_filename=output_filename,
            device=device,
            consent_confirmed=consent,
        )
        return output, json.dumps(metrics, indent=2)

    with gr.Blocks(title="Governed OpenVoice V2 local test") as app:
        gr.Markdown("# Governed OpenVoice V2 local test")
        gr.Markdown(CONSENT_NOTICE)
        with gr.Row():
            reference = gr.Audio(
                label="Authorised reference WAV/MP3",
                type="filepath",
                source="upload",
            )
            with gr.Column():
                text = gr.Textbox(label="Text", lines=5, max_lines=10)
                language = gr.Dropdown(
                    label="Language/accent",
                    choices=list(SUPPORTED_LANGUAGES.keys()),
                    value="British English",
                )
                output_filename = gr.Textbox(
                    label="Output filename",
                    value="openvoice-test",
                )
                device = gr.Dropdown(
                    label="Device",
                    choices=["cpu", "cuda"],
                    value=default_device,
                )
                consent = gr.Checkbox(
                    label="I confirm this is my voice or I have explicit permission",
                    value=False,
                )
                submit = gr.Button("Generate synthetic audio", variant="primary")
        output_audio = gr.Audio(label="Synthetic output", type="filepath")
        metrics = gr.Code(label="Generation evidence", language="json")
        submit.click(
            fn=generate,
            inputs=[reference, text, language, output_filename, device, consent],
            outputs=[output_audio, metrics],
        )
    app.queue(concurrency_count=1, max_size=4)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    host = validate_bind_host(args.host)
    app = build_app(args.device)
    app.launch(
        server_name=host,
        server_port=args.port,
        share=False,
        show_error=True,
        inbrowser=False,
    )


if __name__ == "__main__":
    main()
