from flask import Flask
from flask_login import current_user

from config import Config
from app.extensions import csrf, db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in first."
    login_manager.login_message_category = "warning"

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        # a deactivated user gets logged out on their next request
        return user if user and user.status == "active" else None

    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    from app.listings.routes import listings_bp
    from app.admin.routes import admin_bp
    from app.analytics.routes import analytics_bp
    from app.insights.routes import insights_bp
    from app.notifications.routes import notifications_bp
    from app.places.routes import places_bp
    from app.payments.routes import payments_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(places_bp)
    app.register_blueprint(payments_bp)

    @app.context_processor
    def inject_notifications():
        """The unread notification count shown on the navbar bell."""
        count = 0
        renter = getattr(current_user, "renter", None)
        if renter is not None:
            from app.notifications.services import unread_count

            count = unread_count(renter.renter_id)
        return {"unread_notifications": count}

    @app.context_processor
    def inject_map_config():
        return {"google_maps_api_key": app.config.get("GOOGLE_MAPS_API_KEY", "")}

    return app
