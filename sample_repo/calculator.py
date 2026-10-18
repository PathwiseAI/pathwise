"""Price calculation utilities."""

PRICES = {
    "widget": 10.00,
    "gadget": 25.00,
    "gizmo": 15.50,
}

DISCOUNTS = {
    "SAVE10": 0.10,
    "SAVE20": 0.20,
}


def compute_total(item: str, quantity: int) -> float:
    """Compute the total price for an item and quantity."""
    price = get_unit_price(item)
    return price * quantity


def get_unit_price(item: str) -> float:
    """Look up the unit price for an item."""
    return PRICES.get(item, 0.0)


def apply_discount(total: float, discount_code: str | None) -> float:
    """Apply a discount code to a total."""
    if discount_code is None:
        return total
    rate = DISCOUNTS.get(discount_code, 0.0)
    return total * (1 - rate)
