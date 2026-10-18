"""Order processing service."""
from sample_repo.calculator import compute_total, apply_discount
from sample_repo.persistence import save_order, load_order


def process_order(order_data: dict) -> dict:
    """Process a validated order through the pipeline."""
    total = compute_total(order_data["item"], order_data["quantity"])
    discounted = apply_discount(total, order_data.get("discount_code"))
    order_record = {
        "item": order_data["item"],
        "quantity": order_data["quantity"],
        "total": discounted,
    }
    save_order(order_record)
    return order_record


def get_order_status(order_id: str) -> str:
    """Get the status of an existing order."""
    order = load_order(order_id)
    if order is None:
        return "not_found"
    return order.get("status", "unknown")
