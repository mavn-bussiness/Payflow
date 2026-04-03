from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Service, Transaction, PRICING_TIERS
from datetime import datetime, timedelta
from sqlalchemy import func, extract

dashboard = Blueprint('dashboard', __name__)


@dashboard.route('/dashboard')
@login_required
def home():
    services = Service.query.filter_by(business_id=current_user.id, is_active=True).all()
    transactions = Transaction.query.filter_by(business_id=current_user.id).order_by(Transaction.created_at.desc()).limit(10).all()
    total_paid = db.session.query(func.sum(Transaction.amount)).filter_by(business_id=current_user.id, status='paid').scalar() or 0
    pending_count = Transaction.query.filter_by(business_id=current_user.id, status='pending').count()
    paid_count = Transaction.query.filter_by(business_id=current_user.id, status='paid').count()
    failed_count = Transaction.query.filter_by(business_id=current_user.id, status='failed').count()
    cancelled_count = Transaction.query.filter_by(business_id=current_user.id, status='cancelled').count()

    # Revenue last 7 days (for sparkline)
    seven_days_ago = datetime.utcnow() - timedelta(days=6)
    daily_revenue = []
    daily_labels = []
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        rev = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.business_id == current_user.id,
            Transaction.status == 'paid',
            Transaction.paid_at >= day_start,
            Transaction.paid_at < day_end
        ).scalar() or 0
        daily_revenue.append(float(rev))
        daily_labels.append(day.strftime('%a'))

    # Top services by revenue
    top_services = db.session.query(
        Service.name,
        func.sum(Transaction.amount).label('revenue'),
        func.count(Transaction.id).label('count')
    ).join(Transaction, Transaction.service_id == Service.id).filter(
        Transaction.business_id == current_user.id,
        Transaction.status == 'paid'
    ).group_by(Service.id, Service.name).order_by(func.sum(Transaction.amount).desc()).limit(5).all()

    return render_template('dashboard.html',
                           services=services,
                           transactions=transactions,
                           total_paid=total_paid,
                           pending_count=pending_count,
                           paid_count=paid_count,
                           failed_count=failed_count,
                           cancelled_count=cancelled_count,
                           daily_revenue=daily_revenue,
                           daily_labels=daily_labels,
                           top_services=top_services)


@dashboard.route('/services', methods=['GET', 'POST'])
@login_required
def services():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            pricing_tier = request.form.get('pricing_tier', 'fixed')
            unit_label = request.form.get('unit_label', 'item').strip() or 'item'

            try:
                price = float(request.form.get('price', 0))
                min_price_raw = request.form.get('min_price', '').strip()
                max_price_raw = request.form.get('max_price', '').strip()
                min_price = float(min_price_raw) if min_price_raw else None
                max_price = float(max_price_raw) if max_price_raw else None
            except ValueError:
                flash('Invalid price values.', 'danger')
                return redirect(url_for('dashboard.services'))

            if not name:
                flash('Service name is required.', 'danger')
                return redirect(url_for('dashboard.services'))

            service = Service(
                name=name,
                description=description,
                price=price,
                min_price=min_price,
                max_price=max_price,
                pricing_tier=pricing_tier,
                unit_label=unit_label,
                business_id=current_user.id
            )
            db.session.add(service)
            db.session.commit()
            flash(f'Service "{name}" added successfully.', 'success')

        elif action == 'delete':
            service_id = request.form.get('service_id')
            service = Service.query.filter_by(id=service_id, business_id=current_user.id).first()
            if service:
                service.is_active = False
                db.session.commit()
                flash('Service removed.', 'info')

        elif action == 'edit':
            service_id = request.form.get('service_id')
            service = Service.query.filter_by(id=service_id, business_id=current_user.id).first()
            if service:
                service.name = request.form.get('name', service.name).strip()
                service.description = request.form.get('description', service.description).strip()
                service.pricing_tier = request.form.get('pricing_tier', service.pricing_tier)
                service.unit_label = request.form.get('unit_label', service.unit_label).strip() or 'item'
                try:
                    service.price = float(request.form.get('price', service.price))
                    min_p = request.form.get('min_price', '').strip()
                    max_p = request.form.get('max_price', '').strip()
                    service.min_price = float(min_p) if min_p else None
                    service.max_price = float(max_p) if max_p else None
                except ValueError:
                    pass
                db.session.commit()
                flash('Service updated.', 'success')

        return redirect(url_for('dashboard.services'))

    all_services = Service.query.filter_by(business_id=current_user.id, is_active=True).all()
    return render_template('services.html', services=all_services, pricing_tiers=PRICING_TIERS)


@dashboard.route('/transactions')
@login_required
def transactions():
    status_filter = request.args.get('status', 'all')
    query = Transaction.query.filter_by(business_id=current_user.id)
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    txns = query.order_by(Transaction.created_at.desc()).all()
    return render_template('transactions.html', transactions=txns, status_filter=status_filter)


@dashboard.route('/analytics')
@login_required
def analytics():
    # Last 30 days revenue
    thirty_days_ago = datetime.utcnow() - timedelta(days=29)
    daily_data = []
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        rev = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.business_id == current_user.id,
            Transaction.status == 'paid',
            Transaction.paid_at >= day_start,
            Transaction.paid_at < day_end
        ).scalar() or 0
        count = Transaction.query.filter(
            Transaction.business_id == current_user.id,
            Transaction.status == 'paid',
            Transaction.paid_at >= day_start,
            Transaction.paid_at < day_end
        ).count()
        daily_data.append({'label': day.strftime('%d %b'), 'revenue': float(rev), 'count': count})

    # Status breakdown
    statuses = ['paid', 'pending', 'failed', 'cancelled']
    status_counts = {}
    for s in statuses:
        status_counts[s] = Transaction.query.filter_by(business_id=current_user.id, status=s).count()

    # Payment method breakdown
    method_data = db.session.query(
        Transaction.payment_method,
        func.count(Transaction.id).label('count'),
        func.sum(Transaction.amount).label('revenue')
    ).filter(
        Transaction.business_id == current_user.id,
        Transaction.status == 'paid'
    ).group_by(Transaction.payment_method).all()

    # Top services
    top_services = db.session.query(
        Service.name,
        func.sum(Transaction.amount).label('revenue'),
        func.count(Transaction.id).label('count'),
        func.sum(Transaction.quantity).label('units_sold')
    ).join(Transaction, Transaction.service_id == Service.id).filter(
        Transaction.business_id == current_user.id,
        Transaction.status == 'paid'
    ).group_by(Service.id, Service.name).order_by(func.sum(Transaction.amount).desc()).limit(8).all()

    # Summary stats
    total_paid = db.session.query(func.sum(Transaction.amount)).filter_by(
        business_id=current_user.id, status='paid').scalar() or 0
    total_txns = Transaction.query.filter_by(business_id=current_user.id).count()
    avg_order = (total_paid / status_counts['paid']) if status_counts['paid'] > 0 else 0

    return render_template('analytics.html',
                           daily_data=daily_data,
                           status_counts=status_counts,
                           method_data=method_data,
                           top_services=top_services,
                           total_paid=total_paid,
                           total_txns=total_txns,
                           avg_order=avg_order)
