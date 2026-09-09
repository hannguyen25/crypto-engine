import re
from fastapi import HTTPException, status

SUSPICIOUS_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"system\s*:\s*",
    r"you\s+are\s+now\s+an?\s+unrestricted",
    r"developer\s+mode",
    r"reveal\s+(the\s+)?(api|secret|private)\s+key",
    r"print\s+(your\s+)?system\s+prompt",
    r"jailbreak",
]

COMPILED_INSPECTOR = re.compile(
    "|".join(SUSPICIOUS_PATTERNS), re.IGNORECASE
)

# Regex loại bỏ ký tự điều khiển (ASCII 0-31 ngoại trừ \t, \n, \r) và null-byte \x00
CONTROL_CHAR_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_prompt_input(prompt: str) -> str:
    """Lọc ký tự điều khiển độc hại và kiểm tra tính hợp lệ của prompt."""
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt cannot be empty.",
        )

    # TC-SAN-01: Loại bỏ ký tự điều khiển và null-bytes
    cleaned = CONTROL_CHAR_REGEX.sub("", prompt).strip()

    # TC-SAN-03: Giới hạn độ dài tối đa 1,000 ký tự (trả về 413 hoặc 422)
    if len(cleaned) > 1000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Prompt exceeds maximum allowed length (1000 characters).",
        )

    # TC-SAN-02: Nhận diện mẫu injection kinh điển
    if COMPILED_INSPECTOR.search(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt rejected: Potential prompt injection or adversarial content detected.",
        )

    return cleaned


# Giữ alias để tương thích với các module khác
inspect_prompt_injection = sanitize_prompt_input