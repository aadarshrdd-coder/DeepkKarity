# Tillpoint

A small order desk for a shop: a product catalog, orders with coupons and sales tax, payment webhooks and sales reports. Python 3.10+, standard library only, SQLite for storage.

## Run

```bash
python3 server.py tillpoint.db 8000
```

| Method | Path | Body |
|---|---|---|
| POST | `/orders` | `{"customer", "items": [{"sku", "qty"}], "region", "coupon"}` |
| GET | `/orders/<id>` | |
| POST | `/orders/<id>/cancel` | |
| GET / PUT | `/products/<sku>` | PUT: `{"price_cents"}` |
| POST | `/webhooks/payments` | `{"id", "type": "payment.succeeded", "order_id", "amount_cents"}` |
| GET | `/reports/daily/<YYYY-MM-DD>` | `{"utc_offset_minutes"}` |

Money is integer cents. Timestamps are stored in UTC. The payment provider retries a webhook until it receives a 2xx response.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Layout

```
tillpoint/db.py        schema and time helpers
tillpoint/catalog.py   products and atomic stock reservations
tillpoint/pricing.py   subtotal, coupons, tax
tillpoint/orders.py    create, cancel, ship, list
tillpoint/payments.py  payment webhooks
tillpoint/reports.py   daily sales, top products
tillpoint/api.py       JSON API
server.py              HTTP server
```
