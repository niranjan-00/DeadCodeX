"""
DeadCodeX Main Routes
Serve frontend HTML pages for all routes
"""
from flask import Blueprint, render_template, send_from_directory, current_app
from flask_jwt_extended import jwt_required, get_current_user

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Landing page"""
    return render_template('index.html')


@main_bp.route('/login')
def login_page():
    """Login page"""
    return render_template('login.html')


@main_bp.route('/signup')
def signup_page():
    """Signup page"""
    return render_template('signup.html')


@main_bp.route('/dashboard')
@jwt_required(optional=True)
def dashboard():
    """User dashboard"""
    user = get_current_user()
    return render_template('dashboard.html', user=user.to_dict() if user else None)


@main_bp.route('/upload')
@jwt_required(optional=True)
def upload_page():
    """Upload project page"""
    user = get_current_user()
    return render_template('upload.html', user=user.to_dict() if user else None)


@main_bp.route('/report/<int:scan_id>')
@jwt_required(optional=True)
def report_page(scan_id):
    """Analysis report page"""
    user = get_current_user()
    return render_template('report.html', scan_id=scan_id, user=user.to_dict() if user else None)


@main_bp.route('/cleanup/<int:scan_id>')
@jwt_required(optional=True)
def cleanup_page(scan_id):
    """Cleanup page"""
    user = get_current_user()
    return render_template('cleanup.html', scan_id=scan_id, user=user.to_dict() if user else None)


@main_bp.route('/settings')
@jwt_required(optional=True)
def settings_page():
    """Settings page"""
    user = get_current_user()
    return render_template('settings.html', user=user.to_dict() if user else None)


@main_bp.route('/admin')
@jwt_required(optional=True)
def admin_page():
    """Admin panel page"""
    user = get_current_user()
    return render_template('admin.html', user=user.to_dict() if user else None)


@main_bp.route('/forgot-password')
def forgot_password_page():
    """Forgot password page"""
    return render_template('forgot_password.html')
