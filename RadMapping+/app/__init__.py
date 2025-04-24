from flask import Flask, session
from config import Config
from datetime import datetime

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    from .auth.routes import auth_bp
    from .dashboard.routes import dashboard_bp

    @app.context_processor
    def inject_session():
        return dict(session=session)
    
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}
    def format_ampm(value):
        if value:
            return datetime.strptime(value, "%H:%M:%S").strftime("%I:%M %p")
        return ""

    app.jinja_env.filters['ampm'] = format_ampm

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

    return app