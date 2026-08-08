import unittest

import numpy as np

from onnx_host.embeddings import EmbeddingAdapterError, mean_pool_and_normalize


class MeanPoolingTests(unittest.TestCase):
    def test_ignores_padding_and_normalizes(self):
        tokens = np.asarray(
            [
                [[3.0, 0.0], [0.0, 4.0], [100.0, 100.0]],
                [[2.0, 0.0], [4.0, 0.0], [6.0, 0.0]],
            ],
            dtype=np.float32,
        )
        mask = np.asarray([[1, 1, 0], [1, 1, 1]], dtype=np.int64)

        embeddings = mean_pool_and_normalize(tokens, mask)

        np.testing.assert_allclose(embeddings[0], [0.6, 0.8], atol=1e-6)
        np.testing.assert_allclose(embeddings[1], [1.0, 0.0], atol=1e-6)

    def test_rejects_mismatched_mask(self):
        with self.assertRaises(EmbeddingAdapterError):
            mean_pool_and_normalize(
                np.zeros((1, 2, 3), dtype=np.float32),
                np.ones((1, 3), dtype=np.int64),
            )


if __name__ == "__main__":
    unittest.main()
