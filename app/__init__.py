from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy.pool import NullPool
import os

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app():
    app = Flask(__name__)

    is_production = os.environ.get('FLASK_ENV') == 'production'

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    app.config['DEBUG'] = not is_production

    user = os.getenv('user')
    password = os.getenv('password')
    host = os.getenv('host')
    port = os.getenv('port', '6543' if is_production else '5432')
    dbname = os.getenv('dbname')

    if all([user, password, host, dbname]):
        database_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}?sslmode=require"
    elif is_production:
        raise RuntimeError("Database credentials missing in production")
    else:
        database_url = 'sqlite:///payments.db'

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'poolclass': NullPool}

    # Initialize Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    # Register Blueprints
    from app.routes.auth import auth
    from app.routes.payments import payments
    from app.routes.dashboard import dashboard

    app.register_blueprint(auth)
    app.register_blueprint(payments)
    app.register_blueprint(dashboard)

    return app