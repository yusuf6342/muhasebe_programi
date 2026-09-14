"""Parola hash — düz metin saklanmaz. pbkdf2_sha256 (stdlib)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALG = "pbkdf2_sha256"
_ITERATIONS = 120_000


def hash_parola(parola: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", parola.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS
    )
    return f"{_ALG}${_ITERATIONS}${salt}${dk.hex()}"


def parola_dogrula(parola: str, kayitli_hash: str) -> bool:
    try:
        alg, iter_s, salt, hex_dk = (kayitli_hash or "").split("$", 3)
        if alg != _ALG:
            return False
        iterations = int(iter_s)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", parola.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return hmac.compare_digest(dk.hex(), hex_dk)


def guvenli_parola_uret(uzunluk: int = 12) -> str:
    """İlk kurulum için tek seferlik yönetici parolası."""
    alfabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alfabet) for _ in range(uzunluk))
