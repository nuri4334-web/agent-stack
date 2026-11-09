"""Hidden instruction detector (S3-10): never sends the text over the network."""
from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionResult:
    suspicious: bool
    score: float


def detect(text: str) -> InjectionResult:
    """Whether a normalized text looks like a hidden instruction. On an error or a missing model: suspicious=True."""
    # Skeleton (S3-01). Detector: Görkem, Thu 12 Nov (S3-10).
    return InjectionResult(suspicious=False, score=0.0)
