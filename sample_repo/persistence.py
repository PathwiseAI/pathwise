"""Simple in-memory persistence for demo purposes."""
import uuid

_store: dict[str, dict] = {}


def save_order(order_record: dict) -> str:
    """Save an order and return its ID."""
    order_id = generate_id()
    order_record["id"] = order_id
    order_record["status"] = "completed"
    _store[order_id] = order_record
    return order_id


def load_order(order_id: str) -> dict | None:
    """Load an order by ID."""
    return _store.get(order_id)


def generate_id() -> str:
    """Generate a unique order ID."""
    return str(uuid.uuid4())[:8]
