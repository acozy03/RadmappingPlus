from flask import Blueprint, render_template, session, redirect, url_for

landing_bp = Blueprint('landing', __name__)


def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


@landing_bp.route('/landing')
@login_required
def landing():
    return render_template("landing.html")