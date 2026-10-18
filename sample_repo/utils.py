"""Utility functions not connected to the main order flow."""


def format_currency(amount: float) -> str:
    """Format a float as a currency string."""
    return f"${amount:.2f}"


def sanitize_string(value: str) -> str:
    """Remove leading/trailing whitespace and convert to lowercase."""
    return value.strip().lower()
