from __future__ import annotations

RATES = {
    "USD": 950,
    "PEN": 260,
    "CNY": 130,
    "CLP": 1,
}


def convert_to_clp(amount: float, currency: str) -> float:
    rate = RATES.get((currency or "CLP").upper(), 1)
    return float(amount) * rate

