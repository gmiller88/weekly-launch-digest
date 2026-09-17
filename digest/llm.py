"""Claude calls for the digest: structured output, streaming, and a retry."""

import json
import sys

import anthropic

MODEL = "claude-opus-5"

# A ceiling, not a target — we're billed for what's generated, not what's reserved.
# Set high enough that a full five-entry digest plus thinking never truncates.
MAX_TOKENS = 32000

# Per million tokens, for the run cost summary.
_PRICE_IN = 5.00
_PRICE_OUT = 25.00

_usage = {"input": 0, "output": 0, "calls": 0}


def record_usage(message) -> None:
    _usage["calls"] += 1
    _usage["input"] += getattr(message.usage, "input_tokens", 0) or 0
    _usage["output"] += getattr(message.usage, "output_tokens", 0) or 0


def usage_summary() -> str:
    cost = (
        _usage["input"] / 1_000_000 * _PRICE_IN
        + _usage["output"] / 1_000_000 * _PRICE_OUT
    )
    return (
        f"{_usage['calls']} call(s), {_usage['input']:,} in / "
        f"{_usage['output']:,} out, ~${cost:.2f}"
    )


class StructureError(RuntimeError):
    """The model's response didn't parse or didn't satisfy the caller's check."""


def _text_of(message) -> str:
    return "".join(b.text for b in message.content if b.type == "text")


def structured(
    claude: anthropic.Anthropic,
    prompt: str,
    schema: dict,
    validate=None,
    effort: str = "high",
    max_tokens: int = MAX_TOKENS,
    attempts: int = 2,
    label: str = "request",
) -> dict:
    """Run a prompt that must return JSON matching `schema`.

    Streaming is required at this max_tokens to stay under the SDK's HTTP timeout.
    `validate` may raise StructureError to force a retry on a semantic problem the
    schema can't express (e.g. a truncated final field).
    """
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            with claude.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = stream.get_final_message()

            record_usage(message)

            if message.stop_reason == "max_tokens":
                raise StructureError(
                    f"hit max_tokens ({max_tokens}) — output was truncated"
                )
            if message.stop_reason == "refusal":
                raise StructureError("model declined the request")

            data = json.loads(_text_of(message))
            if validate:
                validate(data)
            return data

        except (StructureError, json.JSONDecodeError) as e:
            last_error = e
            print(
                f"  {label}: attempt {attempt}/{attempts} failed ({e})",
                file=sys.stderr,
            )

    raise StructureError(f"{label} failed after {attempts} attempts: {last_error}")


# Words a sentence doesn't end on — a tell that generation was cut off. Only
# consulted when terminal punctuation is absent, since plenty of complete
# sentences legitimately end "...whatever the target is."
_DANGLING = {
    "and", "or", "the", "a", "an", "to", "of", "with", "that", "which", "for",
    "but", "as", "at", "by", "in", "on", "from", "its", "their", "including",
}


def require_complete(*fields: str):
    """Build a validator asserting each entry's required fields are present and whole.

    Truncation itself is caught upstream by the max_tokens stop_reason and by JSON
    parsing, so this stays conservative: it flags only unambiguous tells, to avoid
    discarding a good entry over a stylistic full stop.
    """

    def _validate(data: dict) -> None:
        for i, entry in enumerate(data.get("entries", [])):
            who = entry.get("company", "?")
            for field in fields:
                value = (entry.get(field) or "").strip()
                if not value:
                    # A deliberately-unscored entry may omit rating rationale.
                    if field == "why_this_rating" and not entry.get("assessable", True):
                        continue
                    raise StructureError(f"entry {i} ({who}) missing '{field}'")

                if value[-1] in ",;:":
                    raise StructureError(
                        f"entry {i} ({who}) field '{field}' ends mid-thought: "
                        f"...{value[-40:]!r}"
                    )
                if value[-1] not in ".!?\"')]":
                    words = value.split()
                    last_word = words[-1].strip(".,;:").lower() if words else ""
                    if last_word in _DANGLING:
                        raise StructureError(
                            f"entry {i} ({who}) field '{field}' ends mid-thought: "
                            f"...{value[-40:]!r}"
                        )

    return _validate
