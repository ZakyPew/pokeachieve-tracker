from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from pokemon_cv.match.types import Candidate


class BaseSpriteDetector(ABC):
    @abstractmethod
    def detect(self, frame_bgr: np.ndarray) -> list[Candidate]:
        raise NotImplementedError
