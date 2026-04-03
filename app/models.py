from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
import uuid


@login_manager.user_loader
def load_user(user_id):
    return Business.query.get(int(user_id))


class Business(UserMixin, db.Model):
    __tablename__ = 'businesses'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    business_type = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    services = db.relationship('Service', backref='business', lazy=True, cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', backref='business', lazy=True, cascade='all, delete-orphan')


PRICING_TIERS = {
    'fixed':      'Fixed Price',
    'negotiable': 'Negotiable',
    'per_unit':   'Per Unit / Per Item',
    'hourly':     'Hourly Rate',
    'daily':      'Daily Rate',
    'custom':     'Custom / Quote',
}


class Service(db.Model):
    __tablename__ = 'services'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(300))
    price = db.Column(db.Float, nullable=False)
    min_price = db.Column(db.Float, nullable=True)
    max_price = db.Column(db.Float, nullable=True)
    pricing_tier = db.Column(db.String(30), default='fixed')
    unit_label = db.Column(db.String(30), default='item')
    currency = db.Column(db.String(10), default='UGX')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    business_id = db.Column(db.Integer, db.ForeignKey('businesses.id'), nullable=False)
    transactions = db.relationship('Transaction', backref='service', lazy=True)

    @property
    def pricing_label(self):
        return PRICING_TIERS.get(self.pricing_tier, 'Fixed Price')


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False,
                          default=lambda: f"PAY-{uuid.uuid4().hex[:8].upper()}")
    customer_name = db.Column(db.String(150), nullable=False)
    customer_email = db.Column(db.String(150))
    customer_phone = db.Column(db.String(20))

    unit_price = db.Column(db.Float, nullable=False, default=0)
    quantity = db.Column(db.Float, nullable=False, default=1)
    discount_type = db.Column(db.String(10), default='none')
    discount_value = db.Column(db.Float, default=0)
    amount = db.Column(db.Float, nullable=False)

    currency = db.Column(db.String(10), default='UGX')
    payment_method = db.Column(db.String(50))
    status = db.Column(db.String(20), default='pending')
    notes = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)

    momo_reference_id = db.Column(db.String(100))   # UUID sent as X-Reference-Id
    momo_transaction_id = db.Column(db.String(100))  # financialTransactionId from MoMo

    business_id = db.Column(db.Integer, db.ForeignKey('businesses.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=True)

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    @property
    def discount_amount(self):
        if self.discount_type == 'percent':
            return self.subtotal * (self.discount_value / 100)
        elif self.discount_type == 'flat':
            return min(self.discount_value, self.subtotal)
        return 0

    @property
    def quantity_label(self):
        qty = self.quantity
        if qty == int(qty):
            return str(int(qty))
        return f"{qty:.2f}"
