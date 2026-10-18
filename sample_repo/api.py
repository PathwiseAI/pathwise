"""Sample API entry point for Pathwise demo."""
from sample_repo.service import process_order, get_order_status


def handle_request(order_data: dict) -> dict:
    """Handle an incoming API request to process an order."""
    validated = validate_input(order_data)
    if not validated:
        return {"error": "Invalid input"}
    result = process_order(validated)
    return {"status": "ok", "result": result}


def handle_status_request(order_id: str) -> dict:
    """Handle a request to check order status."""
    status = get_order_status(order_id)
    return {"order_id": order_id, "status": status}


def validate_input(data: dict) -> dict | None:
    """Validate incoming order data."""
    if not isinstance(data, dict):
        return None
    if "item" not in data or "quantity" not in data:
        return None
    return data
