import requests
import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Transaction, Service
from datetime import datetime

payments = Blueprint('payments', __name__)

MOMO_BASE_URL = os.environ.get('MOMO_BASE_URL', 'https://sandbox.momodeveloper.mtn.com')
MOMO_COLLECTION_URL = f'{MOMO_BASE_URL}/collection'


def momo_get_token():
    """Get a Bearer token from MTN MoMo Collections API."""
    subscription_key = os.environ.get('MOMO_SUBSCRIPTION_KEY', '')
    api_user = os.environ.get('MOMO_API_USER', '')
    api_key = os.environ.get('MOMO_API_KEY', '')
    resp = requests.post(
        f'{MOMO_COLLECTION_URL}/token/',
        auth=(api_user, api_key),
        headers={'Ocp-Apim-Subscription-Key': subscription_key},
        timeout=15
    )
    resp.raise_for_status()
    return resp.json().get('access_token')


def momo_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'X-Target-Environment': os.environ.get('MOMO_ENVIRONMENT', 'sandbox'),
        'Ocp-Apim-Subscription-Key': os.environ.get('MOMO_SUBSCRIPTION_KEY', ''),
        'Content-Type': 'application/json',
    }


def validate_account(phone, token):
    """Returns True if the phone number is an active MoMo account."""
    headers = momo_headers(token)
    headers.pop('Content-Type', None)
    resp = requests.get(
        f'{MOMO_COLLECTION_URL}/v1/accountholder/msisdn/{phone}/active',
        headers=headers,
        timeout=15
    )
    return resp.status_code == 200


def request_to_pay(reference, amount, phone, payer_name, description, token):
    """Initiate a RequesttoPay. Returns the externalId (same as reference)."""
    payload = {
        'amount': str(int(amount)),
        'currency': os.environ.get('MOMO_CURRENCY', 'UGX'),
        'externalId': reference,
        'payer': {
            'partyIdType': 'MSISDN',
            'partyId': phone,
        },
        'payerMessage': description,
        'payeeNote': payer_name,
    }
    resp = requests.post(
        f'{MOMO_COLLECTION_URL}/v1_0/requesttopay',
        json=payload,
        headers={**momo_headers(token), 'X-Reference-Id': reference},
        timeout=15
    )
    return resp.status_code == 202


def get_payment_status(reference, token):
    """Returns the MoMo transaction status dict."""
    resp = requests.get(
        f'{MOMO_COLLECTION_URL}/v1_0/requesttopay/{reference}',
        headers=momo_headers(token),
        timeout=15
    )
    if resp.status_code == 200:
        return resp.json()
    return None


def compute_total(unit_price, quantity, discount_type, discount_value):
    subtotal = unit_price * quantity
    if discount_type == 'percent':
        discount = subtotal * (discount_value / 100)
    elif discount_type == 'flat':
        discount = min(discount_value, subtotal)
    else:
        discount = 0
    return max(0, subtotal - discount)


@payments.route('/payments/new', methods=['GET', 'POST'])
@login_required
def new_payment():
    services = Service.query.filter_by(business_id=current_user.id, is_active=True).all()
    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        customer_email = request.form.get('customer_email', '').strip()
        customer_phone = request.form.get('customer_phone', '').strip()
        service_id = request.form.get('service_id')
        payment_method = request.form.get('payment_method', '')
        notes = request.form.get('notes', '').strip()

        try:
            unit_price = float(request.form.get('unit_price', 0))
            quantity = float(request.form.get('quantity', 1))
            discount_value = float(request.form.get('discount_value', 0))
        except ValueError:
            flash('Invalid numeric values.', 'danger')
            return render_template('new_payment.html', services=services)

        discount_type = request.form.get('discount_type', 'none')
        if discount_type not in ('none', 'percent', 'flat'):
            discount_type = 'none'

        if quantity <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return render_template('new_payment.html', services=services)
        if unit_price <= 0:
            flash('Unit price must be greater than zero.', 'danger')
            return render_template('new_payment.html', services=services)
        if not customer_name or not customer_phone:
            flash('Customer name and phone number are required for Mobile Money.', 'danger')
            return render_template('new_payment.html', services=services)

        # Normalise phone: strip spaces/dashes, ensure it starts with country code
        phone = customer_phone.replace(' ', '').replace('-', '').replace('+', '')

        amount = compute_total(unit_price, quantity, discount_type, discount_value)

        txn = Transaction(
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            unit_price=unit_price,
            quantity=quantity,
            discount_type=discount_type,
            discount_value=discount_value,
            amount=amount,
            payment_method=payment_method or 'MTN Mobile Money',
            notes=notes,
            business_id=current_user.id,
            service_id=int(service_id) if service_id else None,
            status='pending'
        )
        db.session.add(txn)
        db.session.commit()

        service_name = txn.service.name if txn.service else 'Payment'
        description = f'{service_name} x{txn.quantity_label} — {current_user.name}'

        try:
            token = momo_get_token()

            if not validate_account(phone, token):
                flash('Phone number is not a valid active MTN MoMo account.', 'danger')
                txn.status = 'failed'
                db.session.commit()
                return render_template('new_payment.html', services=services)

            # Use a UUID as the MoMo reference (X-Reference-Id must be UUID)
            momo_ref = str(uuid.uuid4())
            txn.momo_reference_id = momo_ref
            db.session.commit()

            success = request_to_pay(momo_ref, amount, phone, customer_name, description, token)
            if success:
                flash(
                    f'Payment request sent to {customer_phone}. '
                    'Ask the customer to approve the prompt on their phone.',
                    'success'
                )
                return redirect(url_for('payments.payment_detail', ref=txn.reference))
            else:
                txn.status = 'failed'
                db.session.commit()
                flash('Failed to send payment request. Check the phone number and try again.', 'danger')

        except requests.RequestException as e:
            flash('Could not reach MTN MoMo API. Check your credentials.', 'danger')
            current_app.logger.error(f'MTN MoMo error: {e}')

        return render_template('new_payment.html', services=services)

    return render_template('new_payment.html', services=services)


@payments.route('/payments/<ref>/check', methods=['POST'])
@login_required
def check_payment_status(ref):
    """Manually poll MTN MoMo for the latest status of a pending transaction."""
    txn = Transaction.query.filter_by(reference=ref, business_id=current_user.id).first_or_404()

    if txn.status != 'pending' or not txn.momo_reference_id:
        flash('Nothing to check for this transaction.', 'info')
        return redirect(url_for('payments.payment_detail', ref=ref))

    try:
        token = momo_get_token()
        data = get_payment_status(txn.momo_reference_id, token)
        if data:
            status = data.get('status', '').upper()
            if status == 'SUCCESSFUL':
                txn.status = 'paid'
                txn.paid_at = datetime.utcnow()
                txn.momo_transaction_id = data.get('financialTransactionId', '')
                db.session.commit()
                flash('Payment confirmed!', 'success')
            elif status == 'FAILED':
                txn.status = 'failed'
                db.session.commit()
                flash(f'Payment failed: {data.get("reason", "Unknown reason")}', 'danger')
            else:
                flash(f'Payment is still {status.lower()}. Ask the customer to check their phone.', 'info')
        else:
            flash('Could not retrieve payment status.', 'danger')
    except requests.RequestException as e:
        flash('Could not reach MTN MoMo API.', 'danger')
        current_app.logger.error(f'MTN MoMo status check error: {e}')

    return redirect(url_for('payments.payment_detail', ref=ref))


@payments.route('/payments/webhook', methods=['POST'])
def momo_webhook():
    """MTN MoMo callback notification endpoint."""
    payload = request.get_json()
    if not payload:
        return jsonify({'status': 'bad request'}), 400

    external_id = payload.get('externalId') or payload.get('referenceId')
    status = payload.get('status', '').upper()

    if not external_id:
        return jsonify({'status': 'ok'}), 200

    txn = Transaction.query.filter_by(momo_reference_id=external_id).first()
    if txn and txn.status == 'pending':
        if status == 'SUCCESSFUL':
            txn.status = 'paid'
            txn.paid_at = datetime.utcnow()
            txn.momo_transaction_id = payload.get('financialTransactionId', '')
            db.session.commit()
        elif status == 'FAILED':
            txn.status = 'failed'
            db.session.commit()

    return jsonify({'status': 'ok'}), 200


@payments.route('/payments/<ref>')
@login_required
def payment_detail(ref):
    txn = Transaction.query.filter_by(reference=ref, business_id=current_user.id).first_or_404()
    return render_template('payment_detail.html', txn=txn)


@payments.route('/payments/<ref>/resend', methods=['POST'])
@login_required
def resend_payment(ref):
    txn = Transaction.query.filter_by(reference=ref, business_id=current_user.id).first_or_404()
    if txn.status not in ('failed', 'cancelled', 'pending'):
        flash('This payment cannot be re-sent.', 'info')
        return redirect(url_for('payments.payment_detail', ref=ref))

    txn.reference = f"PAY-{uuid.uuid4().hex[:8].upper()}"
    txn.status = 'pending'
    txn.momo_reference_id = None
    txn.momo_transaction_id = None
    db.session.commit()

    phone = (txn.customer_phone or '').replace(' ', '').replace('-', '').replace('+', '')
    service_name = txn.service.name if txn.service else 'Payment'
    description = f'{service_name} — {current_user.name}'

    try:
        token = momo_get_token()
        momo_ref = str(uuid.uuid4())
        txn.momo_reference_id = momo_ref
        db.session.commit()

        success = request_to_pay(momo_ref, txn.amount, phone, txn.customer_name, description, token)
        if success:
            flash(f'Payment request resent to {txn.customer_phone}.', 'success')
        else:
            txn.status = 'failed'
            db.session.commit()
            flash('Failed to resend payment request.', 'danger')
    except requests.RequestException:
        flash('Could not reach MTN MoMo API.', 'danger')

    return redirect(url_for('payments.payment_detail', ref=txn.reference))


@payments.route('/payments/<ref>/cancel', methods=['POST'])
@login_required
def cancel_payment(ref):
    txn = Transaction.query.filter_by(reference=ref, business_id=current_user.id).first_or_404()
    if txn.status == 'pending':
        txn.status = 'cancelled'
        db.session.commit()
        flash(f'Payment {ref} cancelled.', 'info')
    return redirect(url_for('dashboard.transactions'))


@payments.route('/api/service/<int:service_id>/price')
@login_required
def get_service_price(service_id):
    service = Service.query.filter_by(id=service_id, business_id=current_user.id).first_or_404()
    return jsonify({
        'price': service.price,
        'name': service.name,
        'pricing_tier': service.pricing_tier,
        'unit_label': service.unit_label or 'item',
        'min_price': service.min_price,
        'max_price': service.max_price,
    })
