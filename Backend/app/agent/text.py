"""
Text helpers shared by the agent: spoken-number normalisation, tolerant JSON
parsing, and a sentence splitter for streamed LLM output.
"""
import json
import re

# ── Spoken numbers → digits ──────────────────────────────────────────────────

_DIGIT_WORDS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUM_WORD = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)"
# A spoken number: a number word followed by more number words ("oh"/"and" allowed inside)
_SPOKEN_NUMBER_RE = re.compile(rf"\b{_NUM_WORD}(?:[\s-]+(?:{_NUM_WORD}|oh|and))*\b", re.IGNORECASE)


def _spoken_number_to_digits(match: re.Match) -> str:
    words = re.split(r"[\s-]+", match.group(0).lower())

    # "one and ..." — a trailing "and"/"oh" belongs to the sentence, not the number
    trailing = []
    while words and words[-1] in ("and", "oh"):
        trailing.insert(0, words.pop())
    suffix = (" " + " ".join(trailing)) if trailing else ""

    number_words = [w for w in words if w != "and"]
    # A lone "one"/"two" is ordinary speech ("no one", "this one") — leave it alone
    if len(number_words) < 2:
        return match.group(0)

    if "hundred" in number_words or "thousand" in number_words:
        # "one thousand and two" → 1002, "two hundred" → 200
        total, current = 0, 0
        for w in number_words:
            if w == "hundred":
                current = max(current, 1) * 100
            elif w == "thousand":
                total += max(current, 1) * 1000
                current = 0
            else:
                current += _DIGIT_WORDS[w]
        return str(total + current) + suffix

    # "one zero zero three" → 1003, "ten oh two" → 1002
    return "".join(str(_DIGIT_WORDS[w]) for w in number_words) + suffix


def normalize_transcript(text: str) -> str:
    """
    Turn spoken numbers into digits so order numbers and phone digits can be
    used by the agent's tools. Everything else is left as the caller said it.
    """
    text = text.strip()

    # Remove commas inside numbers: "1,003" → "1003"
    text = re.sub(r"(\d),(\d)", r"\1\2", text)

    # STT artifact: "1000-3" → "1003"
    text = re.sub(r"\b(1000)-(\d)\b", lambda m: str(1000 + int(m.group(2))), text)

    # STT artifact: "1000 and 3" (heard for "one thousand and three") → "1003"
    text = re.sub(
        r"\b([1-9])000\s+and\s+(\d{1,3})\b",
        lambda m: str(int(m.group(1)) * 1000 + int(m.group(2))),
        text,
    )

    # Spoken numbers → digits
    text = _SPOKEN_NUMBER_RE.sub(_spoken_number_to_digits, text)

    # Collapse spaced or dashed single digits: "1 0 0 3" / "4-5-6-7" → "1003" / "4567"
    text = re.sub(r"\b\d(?:[\s-]+\d\b){2,}", lambda m: re.sub(r"[\s-]+", "", m.group(0)), text)

    # Remove trailing period after a number: "1003." → "1003"
    text = re.sub(r"(\d)\.$", r"\1", text)

    return text


# ── LLM output ───────────────────────────────────────────────────────────────

def parse_json(content) -> dict:
    """Parse an LLM JSON reply, tolerating code fences or text around the object."""
    text = str(content or "")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    parsed = json.loads(match.group(0) if match else text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM reply is not a JSON object")
    return parsed


def clean_for_speech(text: str) -> str:
    """Strip markdown the model may add — it would be read aloud or shown raw."""
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


# Sentence end: . ! ? followed by whitespace, or the Devanagari danda (space optional)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+|(?<=।)\s*")


class SentenceSplitter:
    """
    Feed it streamed text; it hands back each sentence as soon as it is complete,
    so speech synthesis can start before the model has finished the reply.
    """

    def __init__(self):
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        parts = _SENTENCE_END_RE.split(self._buffer)
        self._buffer = parts.pop()          # last piece may be unfinished
        return [s for s in (clean_for_speech(p) for p in parts) if s]

    def flush(self) -> list[str]:
        rest, self._buffer = clean_for_speech(self._buffer), ""
        return [rest] if rest else []
