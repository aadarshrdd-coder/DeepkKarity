import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tillpoint import db, reports
from tillpoint.api import App
from tillpoint.catalog import Catalog, OutOfStock
from tillpoint.payments import PaymentError


class OrderDeskTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.app = App(self.conn)
        self.app.catalog.add_product("MUG", "Mug", 1200, stock=10)
        self.app.catalog.add_product("TEE", "T-shirt", 2500, stock=3)
        self.conn.execute("INSERT INTO coupons (code, kind, value) VALUES ('TEN', 'percent', 10)")

    def test_order_totals_with_tax(self):
        order = self.app.orders.create("ana", [("MUG", 2), ("TEE", 1)], region="CA")
        self.assertEqual(order["subtotal_cents"], 4900)
        self.assertEqual(order["tax_cents"], 355)
        self.assertEqual(order["total_cents"], 5255)
        self.assertEqual(self.app.catalog.get_product("MUG").stock, 8)

    def test_coupon_takes_ten_percent(self):
        order = self.app.orders.create("ana", [("MUG", 1)], coupon_code="TEN")
        self.assertEqual(order["discount_cents"], 120)
        self.assertEqual(order["total_cents"], 1080)

    def test_tax_is_calculated_after_coupon_discount(self):
        order = self.app.orders.create("ana", [("MUG", 1)], region="CA", coupon_code="TEN")

        self.assertEqual(order["subtotal_cents"], 1200)
        self.assertEqual(order["discount_cents"], 120)
        self.assertEqual(order["tax_cents"], 78)
        self.assertEqual(order["total_cents"], 1158)

    def test_out_of_stock(self):
        with self.assertRaises(OutOfStock):
            self.app.orders.create("ana", [("TEE", 4)])
        self.assertEqual(self.app.catalog.get_product("TEE").stock, 3)

    def test_stale_worker_cannot_reserve_stock_twice(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "shared.db")
            first_conn = db.connect(path)
            second_conn = db.connect(path)
            try:
                first_catalog = Catalog(first_conn)
                second_catalog = Catalog(second_conn)
                first_catalog.add_product("ONE", "One left", 100, stock=1)
                first_catalog.get_product("ONE")
                second_catalog.get_product("ONE")

                first_catalog.reserve("ONE", 1)
                with self.assertRaises(OutOfStock) as error:
                    second_catalog.reserve("ONE", 1)

                self.assertEqual(error.exception.available, 0)
                self.assertEqual(second_conn.execute("SELECT stock FROM products WHERE sku = 'ONE'").fetchone()[0], 0)
            finally:
                first_conn.close()
                second_conn.close()

    def test_payment_marks_order_paid(self):
        order = self.app.orders.create("ana", [("MUG", 1)])
        status, payload = self.app.handle("POST", "/webhooks/payments", {
            "id": "evt_1", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 1200})
        self.assertEqual((status, payload["status"]), (200, "paid"))

    def test_payment_webhook_retry_is_idempotent(self):
        order = self.app.orders.create("ana", [("MUG", 1)])
        event = {"id": "evt_retry", "type": "payment.succeeded",
                 "order_id": order["id"], "amount_cents": 1200}

        self.assertEqual(self.app.payments.handle_event(event), "paid")
        self.assertEqual(self.app.payments.handle_event(event), "paid")

        self.assertEqual(self.app.payments.paid_cents(order["id"]), 1200)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0], 1)

    def test_distinct_excess_payment_is_flagged_for_refund(self):
        order = self.app.orders.create("ana", [("MUG", 1)])
        self.app.payments.handle_event(
            {"id": "evt_paid", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 1200})

        status = self.app.payments.handle_event(
            {"id": "evt_extra", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 500})

        self.assertEqual(status, "overpaid")
        saved = self.app.orders.get(order["id"])
        self.assertEqual(saved["status"], "paid")
        self.assertEqual(saved["paid_cents"], 1700)
        self.assertEqual(saved["overpaid_cents"], 500)

    def test_cancel_paid_order_restocks(self):
        order = self.app.orders.create("ana", [("TEE", 2)])
        self.app.payments.handle_event(
            {"id": "evt_2", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 5000})
        self.app.orders.cancel(order["id"])
        self.assertEqual(self.app.catalog.get_product("TEE").stock, 3)

    def test_cancel_pending_order_releases_reserved_stock_and_coupon(self):
        order = self.app.orders.create("ana", [("MUG", 2)], coupon_code="TEN")

        self.app.orders.cancel(order["id"])

        self.assertEqual(self.app.catalog.get_product("MUG").stock, 10)
        self.assertEqual(self.conn.execute("SELECT uses FROM coupons WHERE code = 'TEN'").fetchone()[0], 0)

    def test_daily_sales(self):
        order = self.app.orders.create("ana", [("MUG", 1)])
        noon = datetime(2025, 3, 10, 12, 0, tzinfo=timezone.utc)
        self.app.payments.handle_event(
            {"id": "evt_3", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 1200}, now=noon)
        self.assertEqual(reports.daily_sales(self.conn, "2025-03-10"),
                         {"day": "2025-03-10", "revenue_cents": 1200, "orders": 1})

    def test_daily_sales_uses_local_day_for_positive_utc_offset(self):
        order = self.app.orders.create("ana", [("MUG", 1)])
        morning_in_india = datetime(2025, 3, 10, 2, 0, tzinfo=timezone.utc)
        self.app.payments.handle_event(
            {"id": "evt_india", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 1200},
            now=morning_in_india)

        self.assertEqual(
            reports.daily_sales(self.conn, "2025-03-10", utc_offset_minutes=330),
            {"day": "2025-03-10", "revenue_cents": 1200, "orders": 1},
        )
        self.assertEqual(
            reports.daily_sales(self.conn, "2025-03-09", utc_offset_minutes=330),
            {"day": "2025-03-09", "revenue_cents": 0, "orders": 0},
        )

    def test_price_change(self):
        self.app.handle("PUT", "/products/MUG", {"price_cents": 1500})
        self.assertEqual(self.app.catalog.get_product("MUG").price_cents, 1500)


if __name__ == "__main__":
    unittest.main()
