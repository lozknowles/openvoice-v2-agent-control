from pathlib import Path

from speech.benchmarks.run import (
    REQUIRED_CATEGORIES,
    listening_manifest,
    load_corpus,
    output_root_is_outside_git,
)
from speech.benchmarks.evaluate_asr import word_error_rate


ROOT = Path(__file__).parents[1]


def test_fixed_corpus_covers_every_required_category():
    corpus = load_corpus(ROOT / "speech/benchmarks/corpus.en-GB.json")
    categories = {
        category for case in corpus["cases"] for category in case["categories"]
    }
    assert REQUIRED_CATEGORIES <= categories
    assert len(corpus["cases"]) >= 10


def test_benchmark_refuses_to_write_samples_into_git():
    assert not output_root_is_outside_git(ROOT / "speech/samples/private")


def test_listening_manifest_has_blank_human_fields():
    manifest = listening_manifest(
        [
            {
                "provider": "openvoice",
                "engine": "test",
                "samples": [
                    {
                        "case_id": "short-conversation",
                        "output_path": "/private/sample.wav",
                        "output_sha256": "a" * 64,
                    }
                ],
            }
        ]
    )
    sample = manifest["samples"][0]
    assert sample["intelligibility_notes"] is None
    assert sample["speaker_similarity_notes"] is None
    assert sample["speaker_similarity_applicable"] is True


def test_asr_word_error_rate_is_objective_and_reproducible():
    wer, errors, words = word_error_rate(
        "The quick brown fox.", "The quick fox."
    )
    assert errors == 1
    assert words == 4
    assert wer == 0.25
