"""Amounts in words, Indian style (thousand / lakh / crore) — for the bill."""

from decimal import ROUND_HALF_UP, Decimal

_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven",
    "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _below_thousand(n: int) -> str:
    if n < 100:
        return _below_hundred(n)
    rest = _below_hundred(n % 100)
    return (_ONES[n // 100] + " Hundred" + (" " + rest if rest else "")).strip()


def integer_to_words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand")):
        if n >= size:
            parts.append(f"{_below_hundred(n // size)} {name}")
            n %= size
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def rupees_in_words(amount) -> str:
    """21240 -> 'Twenty One Thousand Two Hundred Forty Rupees Only'."""
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees = int(value)
    paise = int((value - rupees) * 100)
    text = f"{integer_to_words(rupees)} Rupees"
    if paise:
        text += f" and {integer_to_words(paise)} Paise"
    return text + " Only"
