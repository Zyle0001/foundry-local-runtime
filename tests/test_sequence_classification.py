from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from onnx_host import sequence_classification as sequence


@dataclass
class Tensor:
    name: str


class Encoding:
    ids = [1, 2, 0]
    attention_mask = [1, 1, 0]
    type_ids = [0, 0, 0]


class Tokenizer:
    def encode_batch(self, pairs):
        return [Encoding() for _ in pairs]


class Session:
    def __init__(self, logits):
        self.logits = np.asarray(logits, dtype=np.float32)

    def get_inputs(self):
        return [Tensor("input_ids"), Tensor("attention_mask"), Tensor("token_type_ids")]

    def get_outputs(self):
        return [Tensor("logits")]

    def run(self, _, inputs):
        assert inputs["input_ids"].dtype == np.int64
        return [self.logits]


def prepare(monkeypatch, task: str):
    monkeypatch.setattr(sequence, "_adapter", lambda model_id, expected: (Path("."), {"task": task, "output": "logits"}))
    monkeypatch.setattr(sequence, "_tokenizer", lambda root, adapter: Tokenizer())


def test_reranker_returns_one_bounded_score_per_document(monkeypatch) -> None:
    prepare(monkeypatch, "reranker")
    scores = sequence.rerank(Session([[-2.0], [2.0]]), "model", "query", ["first", "second"])
    assert len(scores) == 2
    assert 0 < scores[0] < scores[1] < 1


def test_nli_maps_softmax_labels(monkeypatch) -> None:
    prepare(monkeypatch, "nli")
    scores = sequence.nli(Session([[0.0, 4.0, 0.0]]), "model", [("premise", "hypothesis")])
    assert scores[0]["entailment"] > 0.9
    assert set(scores[0]) == {"contradiction", "entailment", "neutral"}


def test_zero_shot_classification_normalizes_labels(monkeypatch) -> None:
    prepare(monkeypatch, "nli")
    values = sequence.classify(Session([[0.0, 3.0, 0.0], [0.0, 1.0, 0.0]]), "model", ["text"], ["alpha", "beta"])
    assert abs(sum(values[0].values()) - 1.0) < 1e-6
    assert values[0]["alpha"] > values[0]["beta"]
