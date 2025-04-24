from flask import Flask, session, redirect, url_for
from config import Config
from datetime import datetime

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    from .auth.routes import auth_bp
    from .dashboard.routes import dashboard_bp

    # Inject session into Jinja templates
    @app.context_processor
    def inject_session():
        return dict(session=session)

    # Inject 'now' into Jinja templates
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    # Add ampm filter
    def format_ampm(value):
        if value:
            return datetime.strptime(value, "%H:%M:%S").strftime("%I:%M %p")
        return ""
    app.jinja_env.filters['ampm'] = format_ampm

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

    # Redirect root URL to login or dashboard
    @app.route('/')
    def index():
        if "user" in session:
            return redirect(url_for("dashboard.home"))
        return redirect(url_for("auth.login"))

    return app
