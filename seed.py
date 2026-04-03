"""
Seed script — creates a dummy business account with realistic transaction history.
Usage: python seed.py
"""

from app import create_app, db
from app.models import Business, Service, Transaction
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random
import uuid

app = create_app()

DUMMY_EMAIL    = "demo@payflow.com"
DUMMY_PASSWORD = "Demo1234!"

SERVICES = [
    {"name": "Web Design",        "price": 500000,  "pricing_tier": "fixed",    "currency": "UGX"},
    {"name": "Logo Design",       "price": 150000,  "pricing_tier": "fixed",    "currency": "UGX"},
    {"name": "SEO Consultation",  "price": 80000,   "pricing_tier": "hourly",   "currency": "UGX"},
    {"name": "Social Media Mgmt", "price": 200000,  "pricing_tier": "monthly",  "currency": "UGX"},
    {"name": "Photography",       "price": 300000,  "pricing_tier": "per_unit", "currency": "UGX"},
]

CUSTOMERS = [
    ("Alice Nakato",    "alice@example.com",   "0701234567"),
    ("Brian Ssemakula", "brian@example.com",   "0712345678"),
    ("Carol Atim",      "carol@example.com",   "0723456789"),
    ("David Okello",    "david@example.com",   "0734567890"),
    ("Eve Namukasa",    "eve@example.com",     "0745678901"),
    ("Frank Mugisha",   "frank@example.com",   "0756789012"),
    ("Grace Apio",      "grace@example.com",   "0767890123"),
    ("Henry Tumwine",   "henry@example.com",   "0778901234"),
]

PAYMENT_METHODS = ["momo", "cash", "bank_transfer"]
STATUSES        = ["completed", "completed", "completed", "pending", "failed"]  # weighted


def random_date(days_back=180):
    delta = random.randint(0, days_back)
    return datetime.utcnow() - timedelta(days=delta)


def seed():
    with app.app_context():
        # Skip if account already exists
        if Business.query.filter_by(email=DUMMY_EMAIL).first():
            print(f"Demo account already exists: {DUMMY_EMAIL}")
            return

        # Create business
        business = Business(
            name="Demo Agency",
            email=DUMMY_EMAIL,
            password=generate_password_hash(DUMMY_PASSWORD),
            business_type="Agency",
        )
        db.session.add(business)
        db.session.flush()  # get business.id before committing

        # Create services
        service_objs = []
        for s in SERVICES:
            svc = Service(
                name=s["name"],
                price=s["price"],
                pricing_tier=s["pricing_tier"],
                currency=s["currency"],
                business_id=business.id,
            )
            db.session.add(svc)
            service_objs.append(svc)
        db.session.flush()

        # Create ~120 transactions spread over the last 6 months
        for _ in range(120):
            customer = random.choice(CUSTOMERS)
            service  = random.choice(service_objs)
            qty      = random.choice([1, 1, 1, 2, 3])
            unit_price = service.price * random.uniform(0.9, 1.1)
            amount   = round(unit_price * qty, 2)
            status   = random.choice(STATUSES)
            created  = random_date(180)

            txn = Transaction(
                reference=f"PAY-{uuid.uuid4().hex[:8].upper()}",
                customer_name=customer[0],
                customer_email=customer[1],
                customer_phone=customer[2],
                unit_price=round(unit_price, 2),
                quantity=qty,
                amount=amount,
                currency=service.currency,
                payment_method=random.choice(PAYMENT_METHODS),
                status=status,
                created_at=created,
                paid_at=created if status == "completed" else None,
                business_id=business.id,
                service_id=service.id,
            )
            db.session.add(txn)

        db.session.commit()
        print(f"✅ Demo account created!")
        print(f"   Email:    {DUMMY_EMAIL}")
        print(f"   Password: {DUMMY_PASSWORD}")
        print(f"   Services: {len(service_objs)}")
        print(f"   Transactions: 120 (last 6 months)")


if __name__ == "__main__":
    seed()
