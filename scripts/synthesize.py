#!/usr/bin/env python3
"""Command-line entrypoint for the provider-neutral synthesis interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from speech.interface import provider_class, synthesize


PROVIDERS = ("openvoice", "local", "melotts", "elevenlabs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-providers", action="store_true")
    parser.add_argument("--provider", choices=("auto",) + PROVIDERS, default="auto")
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--voice")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--style-emotion")
    parser.add_argument("--style-exaggeration", type=float)
    parser.add_argument("--output-format", choices=("wav", "mp3"), default="wav")
    parser.add_argument("--output-filename", default="speech")
    parser.add_argument("--output-dir")
    parser.add_argument("--language", default="en-GB")
    parser.add_argument("--confirm-consent", action="store_true")
    parser.add_argument("--consent-basis", default="")
    parser.add_argument("--allow-cloud", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_providers:
        records = []
        for name in PROVIDERS:
            adapter_type = provider_class(name)
            available, reason = adapter_type.availability()
            record = {"provider": name, "available": available, "reason": reason}
            if available:
                adapter = adapter_type()
                try:
                    record["capabilities"] = adapter.capabilities().as_dict()
                finally:
                    adapter.close()
            records.append(record)
        print(json.dumps({"providers": records}, indent=2))
        return 0
    if bool(args.text) == bool(args.text_file):
        raise SystemExit("provide exactly one of --text or --text-file")
    if not args.voice:
        raise SystemExit("--voice is required (voice ID/name or authorised reference path)")
    if not args.output_dir:
        raise SystemExit("--output-dir is required and must be outside Git")
    text = (
        args.text
        if args.text is not None
        else Path(args.text_file).read_text(encoding="utf-8")
    )
    style = {}
    if args.style_emotion:
        style["emotion"] = args.style_emotion
    if args.style_exaggeration is not None:
        style["exaggeration"] = args.style_exaggeration
    result = synthesize(
        text=text,
        voice=args.voice,
        provider=args.provider,
        speed=args.speed,
        style=style or None,
        output_format=args.output_format,
        language=args.language,
        output_filename=args.output_filename,
        output_dir=Path(args.output_dir),
        consent_confirmed=args.confirm_consent,
        consent_basis=args.consent_basis,
        allow_cloud=args.allow_cloud,
    )
    print(json.dumps(result.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
