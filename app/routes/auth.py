from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from app.models import Business

auth = Blueprint('auth', __name__)

BUSINESS_TYPES = ['Shop / Supermarket', 'Hospital / Clinic', 'School / Institution', 'Service Provider', 'Restaurant', 'Other']


@auth.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))
    return render_template('index.html')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        business_type = request.form.get('business_type', '')

        if not all([name, email, password, business_type]):
            flash('All fields are required.', 'danger')
            return render_template('register.html', business_types=BUSINESS_TYPES)

        if Business.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'danger')
            return render_template('register.html', business_types=BUSINESS_TYPES)

        hashed_pw = generate_password_hash(password)
        business = Business(name=name, email=email, password=hashed_pw, business_type=business_type)
        db.session.add(business)
        db.session.commit()
        login_user(business)
        flash(f'Welcome, {name}! Your account is ready.', 'success')
        return redirect(url_for('dashboard.home'))

    return render_template('register.html', business_types=BUSINESS_TYPES)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        business = Business.query.filter_by(email=email).first()
        if business and check_password_hash(business.password, password):
            login_user(business)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.home'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
