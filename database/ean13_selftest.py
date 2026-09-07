"""Self-test for EAN-13 helpers (no DB required)."""

from database.ean13 import (
    build_ean13,
    compute_check_digit,
    generate_unique_ean13,
    is_valid_ean13,
    normalize_barcode,
)


def main():
    assert compute_check_digit("869420100001") == 7
    assert is_valid_ean13("8694201000017")
    assert not is_valid_ean13("8694201000010")
    assert build_ean13("869420100001") == "8694201000017"
    assert normalize_barcode("869-4201-00001-7") == "8694201000017"

    first = generate_unique_ean13([])
    assert is_valid_ean13(first)
    second = generate_unique_ean13([first])
    assert second != first
    assert is_valid_ean13(second)

    # Same card style: code used as both stok and barkod still blocks only once in pool
    third = generate_unique_ean13([first, first])
    assert third not in {first}

    print("All EAN-13 tests passed.")
    print(f"sample codes: {first}, {second}, {third}")


if __name__ == "__main__":
    main()
