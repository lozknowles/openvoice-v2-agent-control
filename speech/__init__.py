"""Provider-neutral speech synthesis interface."""

from .interface import (
    ProviderCapabilities,
    SynthesisRequest,
    SynthesisResult,
    synthesize,
)

__all__ = [
    "ProviderCapabilities",
    "SynthesisRequest",
    "SynthesisResult",
    "synthesize",
]
