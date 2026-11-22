"""`transform_text` — TextTransformTool, version `transform_text/1` (tool-contract.md, section 4.3).

Requirements: scenario 4. All rules are Stage 1 (pure function); `execute` has no expected failures.

Profile `title-basic-v1`: split on whitespace (kept exactly as is); in every token the first letter
becomes upper case and the rest lower case. No small-word exceptions: "the lazy dog" -> "The Lazy Dog".
Python's str.title() is NOT used: it capitalises after apostrophes ("o'neill" -> "O'Neill").
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from jobservice import codes
from jobservice.application.tool import ToolContext, ToolResult
from jobservice.tools._params import ParamReader

MAX_TEXT_LENGTH = 10_000
DEFAULT_PROFILE = "title-basic-v1"
PROFILES = {"title-basic-v1": "1"}  # profile id -> profile version
_ALLOWED = ("text", "profile", "author_id", "document_id")
_ALLOWED_CONTROL = {"\t", "\n", "\r"}
_UNSUPPORTED_CATEGORIES = {"Cc", "Cs", "Co", "Cn"}  # control, surrogate, private use, unassigned
_WHITESPACE = re.compile(r"(\s+)")


def unsupported_positions(text: str) -> list[int]:
    return [
        i
        for i, ch in enumerate(text)
        if ch not in _ALLOWED_CONTROL and unicodedata.category(ch) in _UNSUPPORTED_CATEGORIES
    ]


def title_basic_v1(text: str) -> str:
    parts = _WHITESPACE.split(text)
    return "".join(part if part.isspace() or not part else _title_token(part) for part in parts)


def _title_token(token: str) -> str:
    for i, ch in enumerate(token):
        if ch.isalpha():
            return token[:i] + ch.title() + token[i + 1 :].lower()
    return token.lower()


class TextTransformTool:
    name = "transform_text"
    version = "transform_text/1"

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def validate(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        r = ParamReader(params, _ALLOWED)

        text = r.params.get("text")
        if text is None:
            r.fail("text", codes.FIELD_REQUIRED, "Field is required.", None)
        elif not isinstance(text, str):
            r.fail("text", codes.FIELD_TYPE, "Field must be a string.", text)
            text = None
        elif not text.strip():
            r.fail("text", codes.TEXT_EMPTY, "Text must not be empty.", text)
            text = None
        elif len(text) > MAX_TEXT_LENGTH:
            r.fail("text", codes.TEXT_TOO_LONG, f"Text must be at most {MAX_TEXT_LENGTH} characters.", len(text))
            text = None
        else:
            bad = unsupported_positions(text)
            if bad:
                r.fail(
                    "text",
                    codes.UNSUPPORTED_CHARACTERS,
                    "Text contains characters that the profile does not support (positions in rejected_value).",
                    bad[:20],
                )
                text = None

        profile = r.string("profile", required=False, max_len=64)
        if profile is not None and profile not in PROFILES:
            r.fail("profile", codes.PROFILE_NOT_FOUND, f"Profile '{profile}' does not exist.", profile)
        if profile is None:
            profile = DEFAULT_PROFILE

        author_id = r.string("author_id", required=True, max_len=64)
        document_id = r.string("document_id", required=True, max_len=64)

        r.raise_if_errors()
        return {"text": text, "profile": profile, "author_id": author_id, "document_id": document_id}

    def execute(self, params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
        profile = params["profile"]
        return ToolResult.success(
            {
                "text": title_basic_v1(params["text"]),
                "profile": profile,
                "profile_version": PROFILES[profile],
                "author_id": params["author_id"],
                "document_id": params["document_id"],
                "transformed_at": self._clock().isoformat(),
            }
        )
