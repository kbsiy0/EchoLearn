"""Pipeline / API error codes — single source of truth.

Centralizes the error-code taxonomy and the user-facing safe messages
that sanitize raw exception text before it reaches the API. Routers,
services, and the background runner all reference `ErrorCode.X` instead
of bare strings so a typo surfaces at static-analysis time.

`ErrorCode` is a `str, Enum` mix so `ErrorCode.WHISPER_ERROR ==
"WHISPER_ERROR"` and JSON-serialization just emits the string value.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    INVALID_URL = "INVALID_URL"
    VIDEO_UNAVAILABLE = "VIDEO_UNAVAILABLE"
    VIDEO_TOO_LONG = "VIDEO_TOO_LONG"
    FFMPEG_MISSING = "FFMPEG_MISSING"
    DOWNLOAD_ERROR = "DOWNLOAD_ERROR"
    WHISPER_ERROR = "WHISPER_ERROR"
    TRANSLATION_ERROR = "TRANSLATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"


# Codes deliberately omitted (INVALID_URL, VIDEO_UNAVAILABLE, NOT_FOUND)
# fall back to "內部錯誤" via `safe_message()`.
SAFE_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VIDEO_TOO_LONG:    "影片超過 20 分鐘上限",
    ErrorCode.FFMPEG_MISSING:    "伺服器缺少 ffmpeg",
    ErrorCode.DOWNLOAD_ERROR:    "無法下載影片",
    ErrorCode.WHISPER_ERROR:     "字幕轉錄失敗，請稍後再試",
    ErrorCode.TRANSLATION_ERROR: "翻譯失敗，請稍後再試",
    ErrorCode.INTERNAL_ERROR:    "內部錯誤",
}


def safe_message(error_code: ErrorCode | str) -> str:
    """Return a sanitized user-facing message for `error_code`.

    Falls back to INTERNAL_ERROR's message if the code is unknown.
    `ErrorCode(str, Enum)` makes string-keyed lookups equal-by-value.
    """
    return SAFE_MESSAGES.get(error_code, SAFE_MESSAGES[ErrorCode.INTERNAL_ERROR])
