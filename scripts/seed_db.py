"""
seed_db.py — Create the products table and seed test data.

Run once:
  docker compose exec app python scripts/seed_db.py
"""

import asyncio
import os
import asyncpg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://flashsale:flashsale@localhost:5432/flashsale",
)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS products (
    id          SERIAL PRIMARY KEY,
    name        TEXT            NOT NULL,
    description TEXT,
    price       NUMERIC(10, 2)  NOT NULL,
    sale_price  NUMERIC(10, 2),
    stock       INTEGER         NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
"""

HOT_PRODUCT = {
    "id": 123, "name": "iPhone 17 Pro",
    "description": "Flash-sale price — limited stock! 128GB, Titanium Black.",
    "price": 99999.00, "sale_price": 49999.00, "stock": 10000,
}

CONTROL_PRODUCTS = [
    {"id": i, "name": f"Product {i:03d}",
     "description": f"Control product {i} — background traffic.",
     "price": round(999.0 + i * 100, 2), "sale_price": None, "stock": 5000}
    for i in range(1, 21)
]

ALL_PRODUCTS = CONTROL_PRODUCTS + [HOT_PRODUCT]


async def seed():
    print(f"Connecting to: {DATABASE_URL}")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        print("Creating products table...")
        await conn.execute(CREATE_TABLE)
        print(f"Seeding {len(ALL_PRODUCTS)} products...")
        for p in ALL_PRODUCTS:
            await conn.execute(
                """
                INSERT INTO products (id, name, description, price, sale_price, stock)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    name=EXCLUDED.name, description=EXCLUDED.description,
                    price=EXCLUDED.price, sale_price=EXCLUDED.sale_price,
                    stock=EXCLUDED.stock
                """,
                p["id"], p["name"], p["description"],
                p["price"], p["sale_price"], p["stock"],
            )
            label = "HOT " if p["id"] == 123 else "    "
            print(f"  {label} id={p['id']:>4}  name={p['name']}")
        await conn.execute(
            "SELECT setval('products_id_seq', (SELECT MAX(id) FROM products))"
        )
        count = await conn.fetchval("SELECT COUNT(*) FROM products")
        print(f"\nDone. {count} products in database.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())