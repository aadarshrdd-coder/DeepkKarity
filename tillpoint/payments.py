"""Payment provider webhooks. The provider retries a delivery until it gets a 2xx, so events can repeat."""
from . import db


class PaymentError(Exception):
    pass


class Payments:
    def __init__(self, conn):
        self.conn = conn

    def handle_event(self, event, now=None):
        """event: dict(id, type, order_id, amount_cents). Returns the order's status after the event."""
        if event.get("type") != "payment.succeeded":
            return None
        event_id = event.get("id")
        order_id = event.get("order_id")
        amount_cents = event.get("amount_cents")
        if not isinstance(event_id, str) or not event_id:
            raise PaymentError("payment event needs an id")
        if not isinstance(order_id, int) or isinstance(order_id, bool):
            raise PaymentError("payment event needs an integer order_id")
        if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents <= 0:
            raise PaymentError("payment amount must be a positive integer")

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self.conn.execute(
                "SELECT order_id, amount_cents FROM payments WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing is not None:
                if existing["order_id"] != order_id or existing["amount_cents"] != amount_cents:
                    raise PaymentError(f"payment event {event_id} was already used with different details")
                order = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
                status = self._payment_status(order)
                self.conn.execute("COMMIT")
                return status

            order = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order is None:
                raise PaymentError(f"payment for unknown order {order_id}")
            if order["status"] == "cancelled":
                raise PaymentError(f"order {order['id']} is cancelled")
            self.conn.execute(
                "INSERT INTO payments (order_id, event_id, amount_cents, received_at) VALUES (?, ?, ?, ?)",
                (order["id"], event_id, amount_cents, db.to_iso(now or db.utcnow())),
            )
            status = self._payment_status(order)
            self.conn.execute("COMMIT")
            return status
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def _payment_status(self, order):
        paid = self.paid_cents(order["id"])
        if paid > order["total_cents"]:
            return "overpaid"
        if order["status"] == "pending" and paid >= order["total_cents"]:
            self.conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order["id"],))
            return "paid"
        return order["status"]

    def paid_cents(self, order_id):
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS paid FROM payments WHERE order_id = ?", (order_id,)
        ).fetchone()
        return row["paid"]
