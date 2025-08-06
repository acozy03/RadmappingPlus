from flask import Flask, session, redirect, url_for, request
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
        licenses_bp,
        auth_bp,
        shifts_bp,
        audit_bp
    )

    @app.context_processor
    def inject_session():
        return dict(session=session)

    @app.context_processor
    def inject_now():
        current_time = datetime.now()
        print(f"Injecting 'now' into Jinja context: {current_time}") 
        return {'now': current_time}

    def format_ampm(value):
        if value:
            return datetime.strptime(value, "%H:%M:%S").strftime("%I:%M %p")
        return ""
    app.jinja_env.filters['ampm'] = format_ampm

    def shift_minutes_filter(value):
        from datetime import datetime
        if isinstance(value, str):
            try:
                t = datetime.strptime(value, "%H:%M:%S")
            except ValueError:
                try:
                    t = datetime.strptime(value, "%H:%M")
                except ValueError:
                    print(f"Error parsing time string: {value}")
                    return None
            
            return t.hour * 60 + t.minute
            
        elif isinstance(value, datetime):
            return value.hour * 60 + value.minute
            
        return None 

    app.jinja_env.filters['shift_minutes'] = shift_minutes_filter

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
    app.register_blueprint(licenses_bp, url_prefix='/radmapping')
    app.register_blueprint(shifts_bp, url_prefix='/radmapping')
    app.register_blueprint(audit_bp, url_prefix='/radmapping')
    @app.route('/')
    def index():
        print("--- Entering root URL ('/') ---")
        print(f"Session content on root entry: {dict(session)}")

        if session.get("user"):
            print("User is logged in. Redirecting to landing page.")
            return redirect(url_for("landing.landing"))
        
        next_url = request.args.get('next') 
        referrer_url = request.referrer     
        
        print(f"Unauthenticated user at '/'. Request.args.get('next'): {next_url}")
        print(f"Unauthenticated user at '/'. Request.referrer: {referrer_url}")

        final_redirect_url = next_url or referrer_url or url_for('landing.landing')
        
        session['redirect_after_login'] = final_redirect_url
        print(f"User not logged in. Storing 'redirect_after_login': {session['redirect_after_login']}")
        
        return redirect(url_for("auth.login"))

    return app
