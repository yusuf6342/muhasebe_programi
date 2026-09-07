"""EAN-13 helpers: check digit, validation, unique generation (TR prefix 869)."""

from __future__ import annotations


def compute_check_digit(first12: str) -> int:
    if not first12.isdigit() or len(first12) != 12:
        raise ValueError("EAN-13 check digit için ilk 12 hane sayısal olmalıdır.")
    total = 0
    for i, ch in enumerate(first12):
        digit = int(ch)
        total += digit if i % 2 == 0 else digit * 3
    return (10 - (total % 10)) % 10


def is_valid_ean13(code: str) -> bool:
    if not code.isdigit() or len(code) != 13:
        return False
    return compute_check_digit(code[:12]) == int(code[12])


def build_ean13(first12: str) -> str:
    return f"{first12}{compute_check_digit(first12)}"


def normalize_barcode(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def generate_unique_ean13(
    existing_codes: list[str] | set[str] | tuple[str, ...],
    *,
    company_code: str = "4201",
    max_attempts: int = 5000,
) -> str:
    """Format: 869 (TR) + 4-digit company + 5-digit sequence + check digit."""
    company = normalize_barcode(company_code).zfill(4)[:4]
    used = {normalize_barcode(c) for c in existing_codes if normalize_barcode(c)}
    prefix = f"869{company}"
    next_seq = 1
    for code in used:
        if code.startswith(prefix) and len(code) == 13:
            try:
                seq = int(code[7:12])
            except ValueError:
                continue
            if seq >= next_seq:
                next_seq = seq + 1

    for attempt in range(max_attempts):
        seq = f"{(next_seq + attempt) % 100000:05d}"
        candidate = build_ean13(f"{prefix}{seq}")
        if candidate not in used:
            return candidate

    raise ValueError("Benzersiz EAN-13 üretilemedi. Lütfen tekrar deneyin.")
