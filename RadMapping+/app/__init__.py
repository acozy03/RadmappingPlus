from flask import Flask, session, redirect, url_for
from config import Config
from datetime import datetime
from dotenv import load_dotenv
from .admin_required import admin_required


def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.config.from_object(Config)

    from .routes import (
        daily_bp,
        monthly_bp,
        doctors_bp,
        facilities_bp,
        specialties_bp,
        chat_bp,
        vacations_bp,
        info_bp,
        landing_bp,
        contacts_bp,
        visualize_bp,
        licenses_bp,
        auth_bp
    )

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
    app.register_blueprint(daily_bp, url_prefix='/radmapping')
    app.register_blueprint(monthly_bp, url_prefix='/radmapping')
    app.register_blueprint(doctors_bp, url_prefix='/radmapping')
    app.register_blueprint(facilities_bp, url_prefix='/radmapping')
    app.register_blueprint(specialties_bp, url_prefix='/radmapping')
    app.register_blueprint(chat_bp, url_prefix='/radmapping')
    app.register_blueprint(vacations_bp, url_prefix='/radmapping')
    app.register_blueprint(info_bp, url_prefix='/radmapping')
    app.register_blueprint(landing_bp, url_prefix='/radmapping')
    app.register_blueprint(contacts_bp, url_prefix='/radmapping')
    app.register_blueprint(visualize_bp, url_prefix='/radmapping')
    app.register_blueprint(licenses_bp, url_prefix='/radmapping')

    # Redirect root URL to login or landing page
    @app.route('/')
    def index():
        if "user" in session:
            return redirect(url_for("landing.landing"))
        return redirect(url_for("auth.login"))

    return app
