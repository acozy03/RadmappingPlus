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

    def shift_minutes_filter(value):
        from datetime import datetime
        if isinstance(value, str):
            # Try to parse the time string
            try:
                # First try with seconds
                t = datetime.strptime(value, "%H:%M:%S")
            except ValueError:
                try:
                    # Then try without seconds
                    t = datetime.strptime(value, "%H:%M")
                except ValueError:
                    # If both fail, log the error and return None
                    print(f"Error parsing time string: {value}")
                    return None
            
            # Convert to minutes since midnight
            return t.hour * 60 + t.minute
            
        elif isinstance(value, datetime):
            return value.hour * 60 + value.minute
            
        return None  # Return None for invalid input types

    app.jinja_env.filters['shift_minutes'] = shift_minutes_filter

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

    # Redirect root URL to login or landing page
    @app.route('/')
    def index():
        if "user" in session:
            return redirect(url_for("dashboard.landing"))
        return redirect(url_for("auth.login"))

    return app
