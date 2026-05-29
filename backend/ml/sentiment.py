import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class SentimentResult:
    label: str      # "POSITIVE" | "NEGATIVE" | "NEUTRAL"
    score: float    # 0.0 – 1.0
    reasoning: str

# Lazy loading FinBERT components
_finbert_pipeline = None
_finbert_attempted = False

def _get_finbert():
    global _finbert_pipeline, _finbert_attempted
    if _finbert_pipeline is not None:
        return _finbert_pipeline
    if _finbert_attempted:
        return None
    _finbert_attempted = True
    try:
        from transformers import pipeline
        logger.info("Initializing FinBERT sentiment model (ProsusDE/finbert)...")
        # We specify device=-1 to run on CPU locally; safe for all users
        _finbert_pipeline = pipeline("sentiment-analysis", model="ProsusDE/finbert", device=-1)
        logger.info("FinBERT model successfully loaded.")
        return _finbert_pipeline
    except Exception as e:
        logger.debug("FinBERT could not be loaded: %s. Using keyword sentiment engine.", e)
        return None


POSITIVE_KEYWORDS = {
    "profit": 0.8, "profits": 0.8, "earnings": 0.75, "revenue": 0.7,
    "growth": 0.75, "surge": 0.85, "gain": 0.8, "gains": 0.8,
    "rally": 0.85, "dividend": 0.8, "expansion": 0.7, "upgrade": 0.8,
    "outperform": 0.85, "strong": 0.65, "record": 0.7, "beat": 0.75,
    "bullish": 0.9, "boost": 0.7, "acquisition": 0.65, "approved": 0.65,
    "recovered": 0.7, "increased": 0.7, "rises": 0.75, "soars": 0.85,
    "upside": 0.75, "positive": 0.65, "optimistic": 0.7,
}

NEGATIVE_KEYWORDS = {
    "loss": 0.85, "losses": 0.85, "decline": 0.8, "drop": 0.8,
    "plunge": 0.9, "crash": 0.95, "debt": 0.6, "default": 0.9,
    "downgrade": 0.85, "underperform": 0.85, "bearish": 0.9,
    "warning": 0.75, "weak": 0.65, "miss": 0.75, "shortfall": 0.8,
    "deficit": 0.75, "lawsuit": 0.7, "fraud": 0.95, "scandal": 0.85,
    "inflation": 0.6, "recession": 0.85, "layoffs": 0.75,
    "depreciated": 0.7, "fell": 0.75, "sinks": 0.8, "tumbles": 0.85,
}

NEGATION_WORDS = {"not", "no", "never", "despite", "without", "against"}


def analyse(text: str) -> SentimentResult:
    if not text or not text.strip():
        return SentimentResult("NEUTRAL", 0.5, "No text provided.")

    # 1. Try FinBERT
    nlp = _get_finbert()
    if nlp is not None:
        try:
            truncated_text = text[:1500]
            prediction = nlp(truncated_text)[0]
            label = prediction["label"].upper()
            score = round(float(prediction["score"]), 3)
            return SentimentResult(
                label=label,
                score=score,
                reasoning=f"FinBERT NLP classification (confidence: {score:.0%})."
            )
        except Exception as e:
            logger.debug("FinBERT inference failed: %s. Falling back to keywords.", e)

    # 2. Fallback to Keyword analysis
    words = re.findall(r"\b\w+\b", text.lower())
    pos_score, neg_score = 0.0, 0.0
    matched_pos, matched_neg = [], []

    for i, word in enumerate(words):
        window  = set(words[max(0, i - 3):i])
        negated = bool(window & NEGATION_WORDS)

        if word in POSITIVE_KEYWORDS:
            weight = POSITIVE_KEYWORDS[word]
            if negated:
                neg_score += weight * 0.7
                matched_neg.append(f"not {word}")
            else:
                pos_score += weight
                matched_pos.append(word)

        if word in NEGATIVE_KEYWORDS:
            weight = NEGATIVE_KEYWORDS[word]
            if negated:
                pos_score += weight * 0.5
                matched_pos.append(f"not {word}")
            else:
                neg_score += weight
                matched_neg.append(word)

    total = pos_score + neg_score
    if total == 0:
        return SentimentResult("NEUTRAL", 0.50, "No strong financial signals detected.")

    pos_ratio = pos_score / total
    neg_ratio = neg_score / total
    confidence = round(min(0.97, max(0.50, 0.50 + (max(pos_ratio, neg_ratio) - 0.50) * 0.94)), 3)

    if pos_ratio > neg_ratio:
        return SentimentResult("POSITIVE", confidence, f"Positive signals: {', '.join(matched_pos[:4])}.")
    elif neg_ratio > pos_ratio:
        return SentimentResult("NEGATIVE", confidence, f"Negative signals: {', '.join(matched_neg[:4])}.")
    return SentimentResult("NEUTRAL", 0.50, "Mixed signals — no clear directional bias.")


def aggregate_sentiment(results: list) -> SentimentResult:
    if not results:
        return SentimentResult("NEUTRAL", 0.50, "No data.")
    pos = sum(1 for r in results if r.label == "POSITIVE")
    neg = sum(1 for r in results if r.label == "NEGATIVE")
    avg = sum(r.score for r in results) / len(results)
    if pos > neg:
        return SentimentResult("POSITIVE", round(avg, 3), f"{pos}/{len(results)} positive signals.")
    elif neg > pos:
        return SentimentResult("NEGATIVE", round(avg, 3), f"{neg}/{len(results)} negative signals.")
    return SentimentResult("NEUTRAL", 0.50, "Equal positive and negative signals.")
