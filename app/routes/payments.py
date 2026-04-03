import requests
import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Transaction, Service
from datetime import datetime

payments = Blueprint('payments', __name__)

FLW_BASE_URL = 'https://api.flutterwave.com/v3'


def flw_headers():
    return {
        'Authorization': f'Bearer {os.environ.get("FLW_SECRET_KEY", "")}',
        'Content-Type': 'application/json'
    }


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

        amount = compute_total(unit_price, quantity, discount_type, discount_value)

        if not customer_name or not customer_email:
            flash('Customer name and email are required.', 'danger')
            return render_template('new_payment.html', services=services)

        txn = Transaction(
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            unit_price=unit_price,
            quantity=quantity,
            discount_type=discount_type,
            discount_value=discount_value,
            amount=amount,
            payment_method=payment_method,
            notes=notes,
            business_id=current_user.id,
            service_id=int(service_id) if service_id else None,
            status='pending'
        )
        db.session.add(txn)
        db.session.commit()

        redirect_url = url_for('payments.payment_detail', ref=txn.reference, _external=True)
        service_name = txn.service.name if txn.service else 'Payment'

        payload = {
            'tx_ref': txn.reference,
            'amount': amount,
            'currency': 'UGX',
            'redirect_url': redirect_url,
            'customer': {
                'email': customer_email,
                'phonenumber': customer_phone,
                'name': customer_name
            },
            'customizations': {
                'title': current_user.name,
                'description': f'{service_name} x{txn.quantity_label}',
            },
            'payment_options': 'mobilemoney,card,banktransfer',
            'meta': {'transaction_db_id': txn.id, 'business_id': current_user.id}
        }

        try:
            resp = requests.post(f'{FLW_BASE_URL}/payments', json=payload, headers=flw_headers(), timeout=15)
            data = resp.json()
            if data.get('status') == 'success':
                txn.flw_payment_link = data['data']['link']
                db.session.commit()
                return redirect(data['data']['link'])
            else:
                flash(f'Payment gateway error: {data.get("message", "Unknown error")}', 'danger')
        except requests.RequestException as e:
            flash('Could not reach payment gateway. Check your API keys.', 'danger')
            current_app.logger.error(f'Flutterwave error: {e}')

        return render_template('new_payment.html', services=services)

    return render_template('new_payment.html', services=services)


@payments.route('/payments/callback')
def flw_callback():
    status = request.args.get('status')
    tx_ref = request.args.get('tx_ref')
    transaction_id = request.args.get('transaction_id')

    txn = Transaction.query.filter_by(reference=tx_ref).first()
    if not txn:
        flash('Transaction not found.', 'danger')
        return redirect(url_for('dashboard.home'))

    if status == 'successful' and transaction_id:
        try:
            resp = requests.get(
                f'{FLW_BASE_URL}/transactions/{transaction_id}/verify',
                headers=flw_headers(), timeout=15
            )
            data = resp.json()
            flw_data = data.get('data', {})
            if (data.get('status') == 'success'
                    and flw_data.get('status') == 'successful'
                    and float(flw_data.get('amount', 0)) >= txn.amount
                    and flw_data.get('currency') == 'UGX'):
                txn.status = 'paid'
                txn.paid_at = datetime.utcnow()
                txn.flw_transaction_id = str(transaction_id)
                db.session.commit()
                flash(f'Payment confirmed! Reference: {txn.reference}', 'success')
            else:
                txn.status = 'failed'
                db.session.commit()
                flash('Payment verification failed. Contact support.', 'danger')
        except requests.RequestException:
            flash('Could not verify payment. Check transaction status.', 'danger')
    elif status == 'cancelled':
        txn.status = 'cancelled'
        db.session.commit()
        flash('Payment was cancelled.', 'info')
    else:
        txn.status = 'failed'
        db.session.commit()
        flash('Payment was not completed.', 'danger')

    return redirect(url_for('payments.payment_detail', ref=txn.reference))


@payments.route('/payments/webhook', methods=['POST'])
def flw_webhook():
    secret_hash = os.environ.get('FLW_WEBHOOK_SECRET', '')
    signature = request.headers.get('verif-hash', '')
    if not secret_hash or signature != secret_hash:
        return jsonify({'status': 'unauthorized'}), 401

    payload = request.get_json()
    if not payload:
        return jsonify({'status': 'bad request'}), 400

    event = payload.get('event')
    data = payload.get('data', {})

    if event == 'charge.completed' and data.get('status') == 'successful':
        tx_ref = data.get('tx_ref')
        txn = Transaction.query.filter_by(reference=tx_ref).first()
        if txn and txn.status != 'paid':
            txn.status = 'paid'
            txn.paid_at = datetime.utcnow()
            txn.flw_transaction_id = str(data.get('id', ''))
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
    txn.flw_payment_link = None
    db.session.commit()

    redirect_url = url_for('payments.payment_detail', ref=txn.reference, _external=True)
    payload = {
        'tx_ref': txn.reference,
        'amount': txn.amount,
        'currency': 'UGX',
        'redirect_url': redirect_url,
        'customer': {
            'email': txn.customer_email or f'{txn.reference.lower()}@payflow.ug',
            'phonenumber': txn.customer_phone or '',
            'name': txn.customer_name
        },
        'customizations': {'title': current_user.name},
        'payment_options': 'mobilemoney,card,banktransfer',
    }

    try:
        resp = requests.post(f'{FLW_BASE_URL}/payments', json=payload, headers=flw_headers(), timeout=15)
        data = resp.json()
        if data.get('status') == 'success':
            txn.flw_payment_link = data['data']['link']
            db.session.commit()
            return redirect(data['data']['link'])
        else:
            flash(f'Gateway error: {data.get("message")}', 'danger')
    except requests.RequestException:
        flash('Could not reach payment gateway.', 'danger')

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
