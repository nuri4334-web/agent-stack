"""Hidden instruction (prompt injection) detector (S3-10). Never sends the text over the network.

detect(text) -> InjectionResult(suspicious, score)

Flow:
1. normalize(text) (the shared filter normalize: invisible characters removed).
2. Rule layer: a small list of explicit Turkish/English redirections ("ignore previous instructions",
   "önceki talimatları yok say", "reveal your system prompt", fake system tags ...).
3. Local model: Horizon-Labs/prompt-injection-guard-small at a pinned revision, loaded once, offline only.
4. suspicious = rule hit OR model injection probability >= THRESHOLD.
5. Fail-closed: if the model is missing, cannot be loaded, raises, returns an invalid output or the text is too long
   to be fully covered, suspicious=True.

Score:
- score is the model's INJECTION probability in [0, 1] (the maximum over all windows of the text) whenever the model
  ran and returned a valid output, also when a rule hit too: a rule never changes the score.
- score is NO_SCORE (-1.0) when the model gave no valid output (missing, load error, inference error, invalid output,
  text too long) or did not run (empty text). NO_SCORE is not a probability: it never means "clean" or "certain".
- The decision is always `suspicious`; a caller must not re-derive it from `score`.

Offline: the loader sets HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 and loads with local_files_only=True and
trust_remote_code=False. The model is downloaded once at setup time (see server/README.md), never here.
The heavy libraries (torch, transformers) are optional: server/requirements-detector.txt. Without them detect()
fails closed.

Logs and errors never contain the text or a part of it; only the error type.
"""
import logging
import math
import os
import re
import threading
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .normalize import normalize

logger = logging.getLogger(__name__)

MODEL_ID = "Horizon-Labs/prompt-injection-guard-small"
MODEL_REVISION = "5ed691c28fc37db51f4e80fb81311b7d2b5d4646"
# Label names from the model's config.json (id2label {"0": "SAFE", "1": "INJECTION"}); the index is read from the
# loaded config at start, never assumed.
INJECTION_LABEL = "INJECTION"
SAFE_LABEL = "SAFE"

THRESHOLD = 0.5  # The model card's default threshold.
NO_SCORE = -1.0  # The model gave no valid probability; see the module docstring.

# Long text: overlapping token windows cover the whole text (the model card's windowing: 2048 tokens, 512 overlap).
# More windows than MAX_WINDOWS, or more characters than MAX_CHARS, is not cut: it fails closed.
WINDOW_TOKENS = 2048
WINDOW_OVERLAP = 512
MAX_WINDOWS = 8
MAX_CHARS = 60_000


@dataclass(frozen=True)
class InjectionResult:
    suspicious: bool
    score: float


class Classifier(Protocol):
    """What the detector needs from a model: one INJECTION probability per window, the windows covering all text."""

    def predict(self, text: str) -> Sequence[float]: ...


class DetectorUnavailable(Exception):
    """The model cannot give a verdict (raised without the text in the message)."""


# --- Rule layer ----------------------------------------------------------------------------------------------------

# Rules match a folded form of the text: NFKC, lower case, Turkish letters folded to ASCII (ı/İ -> i, ş -> s,
# ğ -> g, ü -> u, ö -> o, ç -> c), whitespace runs as one space. So "ÖNCEKİ TALİMATLARI" and "onceki talimatlari"
# match the same pattern. The folded form is used only for matching, never returned.
_TR_FOLD = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "â": "a", "î": "i", "û": "u"})
_SPACES = re.compile(r"\s+")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("İ", "i").replace("I", "i").lower()
    # lower() turns "İ" into "i" + combining dot; drop the combining dot left by any other path.
    text = text.replace("̇", "")
    return _SPACES.sub(" ", text.translate(_TR_FOLD))


# Rules are deliberately narrow: they must not fire on ordinary technical talk ("enable developer mode on the phone",
# "don't ignore the lint rules", "önceki kuralları unutmuşum"). Anything subtler is the model's job.
_OLD = r"(?:previous|prior|above|earlier|preceding|original|initial|system|all)"
_ORDERS = r"(?:instructions?|prompts?|guidelines|directives|rules)"
_TR_OLD = r"(?:onceki|yukaridaki|evvelki|tum|butun|sistem)"
_TR_ORDERS = r"(?:talimat|komut|kural|yonerge|direktif)\w*"
_TR_DROP = (r"(?:yok ?say(?:in|iniz)?|unut(?:un|unuz)?|gormezden gel(?:in|iniz)?|dikkate alma(?:yin|yiniz)?"
            r"|gecersiz say(?:in)?|cigne(?:yin)?)\b")

_RULES = tuple(re.compile(p) for p in (
    # EN: drop the earlier instructions ("ignore all previous instructions", "disregard the system prompt").
    rf"\b(?:ignore|disregard|forget|override)\b (?:(?:all|any|the|your|of|my|these) ){{0,3}}{_OLD}"
    rf"(?: \w+)? {_ORDERS}\b",
    # EN: extract the system prompt / hidden instructions ("reveal your system prompt").
    r"\b(?:reveal|show|print|output|repeat|leak|display|dump|tell) (?:me |us )?your (?:\w+ )?"
    r"(?:system prompt|system message|hidden instructions|initial instructions)",
    # EN: role hijack ("you are now in DAN mode"). "developer mode" alone is ordinary phone/browser talk.
    r"\byou are now (?:in )?(?:an? )?(?:unrestricted|unfiltered|jailbroken|dan|jailbreak)\b",
    r"\b(?:enable|enter|activate|switch to) (?:dan|jailbreak) mode\b",
    # Fake chat-template markers inside content.
    r"<\|(?:im_start|im_end|system|endoftext)\|>|\[/?inst\]|<start_of_turn>",
    # TR: drop the earlier instructions ("önceki talimatları yok say", "tüm kuralları unut").
    rf"\b{_TR_OLD}(?: \w+){{0,2}} {_TR_ORDERS} (?:\w+ )?{_TR_DROP}",
    # TR: extract the system prompt ("sistem istemini göster", "gizli talimatlarını yaz").
    r"(?:sistem (?:istem|prompt)\w*|gizli (?:talimat|kural)\w*) (?:\w+ ){0,2}"
    r"(?:goster|yaz|soyle|acikla|paylas|ver|ifsa et|tekrarla)\b",
    # TR: role hijack ("artık kısıtlamasız bir yapay zekasın", "jailbreak moduna geç").
    r"\b(?:jailbreak|dan) modu\w* (?:gec|gir)\b",
    r"\bartik (?:sen )?(?:bir )?(?:kisitlamasiz|filtresiz|kuralsiz|sansursuz) (?:bir )?"
    r"(?:asistan|yapay zeka|model|ai)",
))


def matches_rules(text: str) -> bool:
    """Whether a text matches an explicit redirection rule (the text should already be normalized)."""
    folded = _fold(text)
    return any(rule.search(folded) for rule in _RULES)


# --- Model ---------------------------------------------------------------------------------------------------------

def _injection_index(id2label: Mapping) -> int:
    """The output index of INJECTION, checked against the expected two-label config."""
    labels = {int(k): str(v).upper() for k, v in dict(id2label).items()}
    if sorted(labels) != [0, 1] or set(labels.values()) != {SAFE_LABEL, INJECTION_LABEL}:
        raise DetectorUnavailable("unexpected model labels")
    return next(i for i, label in labels.items() if label == INJECTION_LABEL)


class _HFClassifier:
    """transformers model + fast tokenizer; overlapping windows cover the whole text."""

    def __init__(self, tokenizer, model, torch, injection_index: int):
        self._tokenizer = tokenizer
        self._model = model
        self._torch = torch
        self._index = injection_index

    def predict(self, text: str) -> list[float]:
        encoded = self._tokenizer(
            text, truncation=True, max_length=WINDOW_TOKENS, stride=WINDOW_OVERLAP,
            return_overflowing_tokens=True, padding=True, return_tensors="pt",
        )
        windows = int(encoded["input_ids"].shape[0])
        if windows > MAX_WINDOWS:
            raise DetectorUnavailable("text needs too many windows")
        with self._torch.no_grad():
            logits = self._model(input_ids=encoded["input_ids"], attention_mask=encoded["attention_mask"]).logits
        probabilities = self._torch.softmax(logits.float(), dim=-1)[:, self._index]
        return [float(p) for p in probabilities.tolist()]


def _load_default_model() -> Classifier:
    """Load the pinned model from the local Hugging Face cache only. Raises if anything is missing."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION, local_files_only=True, trust_remote_code=False,
    )
    if not getattr(tokenizer, "is_fast", False):
        raise DetectorUnavailable("a fast tokenizer is needed for windowing")
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION, local_files_only=True, trust_remote_code=False, use_safetensors=True,
    )
    model.eval()
    return _HFClassifier(tokenizer, model, torch, _injection_index(model.config.id2label))


# Lazy, thread-safe, once: the first detect() loads; a failed load is remembered (fail-closed until restart).
_loader: Callable[[], Classifier] = _load_default_model
_lock = threading.Lock()
_classifier: Classifier | None = None
_load_failed = False


def _get_classifier() -> Classifier:
    global _classifier, _load_failed
    if _classifier is not None:
        return _classifier
    with _lock:
        if _classifier is None and not _load_failed:
            try:
                _classifier = _loader()
            except Exception as error:  # noqa: BLE001 - any load problem means "no model"
                _load_failed = True
                logger.warning("Injection detector model unavailable (%s); detect() fails closed.",
                               type(error).__name__)
        if _classifier is None:
            raise DetectorUnavailable("model unavailable")
        return _classifier


def warm_up() -> bool:
    """Load the model now (e.g. at server start) instead of on the first detect(); True if it is available."""
    try:
        _get_classifier()
        return True
    except DetectorUnavailable:
        return False


def _reset_for_tests() -> None:
    global _classifier, _load_failed, _loader
    with _lock:
        _classifier, _load_failed, _loader = None, False, _load_default_model


def _model_score(text: str) -> float:
    """The maximum INJECTION probability over the windows; raises DetectorUnavailable on any problem."""
    if len(text) > MAX_CHARS:
        raise DetectorUnavailable("text too long")
    classifier = _get_classifier()
    try:
        probabilities = list(classifier.predict(text))
    except DetectorUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        logger.warning("Injection detector inference failed (%s); fail closed.", type(error).__name__)
        raise DetectorUnavailable("inference failed") from None
    if not probabilities or not all(
        isinstance(p, float) and math.isfinite(p) and 0.0 <= p <= 1.0 for p in probabilities
    ):
        logger.warning("Injection detector returned an invalid output; fail closed.")
        raise DetectorUnavailable("invalid model output")
    return max(probabilities)


def detect(text: str) -> InjectionResult:
    """Whether a text looks like a hidden instruction. On an error or a missing model: suspicious=True."""
    try:
        clean = normalize(text)
        rule_hit = matches_rules(clean)
        if not clean.strip():
            return InjectionResult(suspicious=False, score=NO_SCORE)
        try:
            score = _model_score(clean)
        except DetectorUnavailable:
            return InjectionResult(suspicious=True, score=NO_SCORE)
        return InjectionResult(suspicious=rule_hit or score >= THRESHOLD, score=score)
    except Exception as error:  # noqa: BLE001 - the detector itself must never let a text through on a bug
        logger.warning("Injection detector error (%s); fail closed.", type(error).__name__)
        return InjectionResult(suspicious=True, score=NO_SCORE)
