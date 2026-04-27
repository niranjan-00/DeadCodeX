"""
DeadCodeX Authentication Routes
JWT-based user registration, login, logout, and profile management
"""
import re
from datetime import datetime
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    create_access_token, create_refresh_token, jwt_required, 
    get_jwt_identity, get_current_user, unset_jwt_cookies
)
from models import User, ActivityLog
from extensions import db

auth_bp = Blueprint('auth', __name__)

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def validate_email(email):
    return bool(EMAIL_REGEX.match(email))


def validate_password(password):
    """Password must be at least 8 chars with mix of letters and numbers"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Za-z]', password):
        return False, "Password must contain at least one letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, "Valid"


def log_activity(user_id, action, entity_type=None, entity_id=None, details=None):
    """Log user activity"""
    try:
        log = ActivityLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Failed to log activity: {e}")


@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user"""
    data = request.get_json() or {}
    
    # Validate required fields
    email = data.get('email', '').strip().lower()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')
    full_name = data.get('full_name', '').strip()
    
    errors = {}
    if not email:
        errors['email'] = 'Email is required'
    elif not validate_email(email):
        errors['email'] = 'Invalid email format'
    
    if not username:
        errors['username'] = 'Username is required'
    elif len(username) < 3:
        errors['username'] = 'Username must be at least 3 characters'
    elif not re.match(r'^[a-zA-Z0-9_]+$', username):
        errors['username'] = 'Username can only contain letters, numbers, and underscores'
    
    if not password:
        errors['password'] = 'Password is required'
    else:
        valid, msg = validate_password(password)
        if not valid:
            errors['password'] = msg
    
    if errors:
        return jsonify({'success': False, 'message': 'Validation failed', 'errors': errors}), 400
    
    # Check existing users
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered', 'errors': {'email': 'Email already in use'}}), 409
    
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': 'Username already taken', 'errors': {'username': 'Username already taken'}}), 409
    
    # Create user
    user = User(
        email=email,
        username=username,
        password_hash=generate_password_hash(password),
        full_name=full_name or None
    )
    db.session.add(user)
    db.session.commit()
    
    # Generate tokens - identity must be string for newer PyJWT
    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    
    log_activity(user.id, 'user_registered')
    
    return jsonify({
        'success': True,
        'message': 'Registration successful',
        'data': {
            'user': user.to_dict(),
            'tokens': {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_type': 'Bearer'
            }
        }
    }), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    """Authenticate user and return JWT tokens"""
    data = request.get_json() or {}
    
    identifier = data.get('email', '').strip().lower()
    password = data.get('password', '')
    remember = data.get('remember', False)
    
    if not identifier or not password:
        return jsonify({'success': False, 'message': 'Email and password are required'}), 400
    
    # Find user by email or username
    user = User.query.filter(
        db.or_(User.email == identifier, User.username == identifier)
    ).first()
    
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
    
    if not user.is_active:
        return jsonify({'success': False, 'message': 'Account is deactivated'}), 403
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.session.commit()
    
    # Generate tokens - identity must be string for newer PyJWT
    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    
    log_activity(user.id, 'user_login')
    
    response = jsonify({
        'success': True,
        'message': 'Login successful',
        'data': {
            'user': user.to_dict(),
            'tokens': {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_type': 'Bearer'
            }
        }
    })
    
    return response, 200


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user or not user.is_active:
        return jsonify({'success': False, 'message': 'User not found or inactive'}), 401
    
    access_token = create_access_token(identity=user.id)
    
    return jsonify({
        'success': True,
        'message': 'Token refreshed',
        'data': {
            'access_token': access_token,
            'token_type': 'Bearer'
        }
    })


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout user (client should discard tokens)"""
    current_user = get_current_user()
    if current_user:
        log_activity(current_user.id, 'user_logout')
    
    response = jsonify({'success': True, 'message': 'Logout successful'})
    unset_jwt_cookies(response)
    return response


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user_profile():
    """Get current authenticated user"""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    return jsonify({
        'success': True,
        'data': {'user': current_user.to_dict()}
    })


@auth_bp.route('/me', methods=['PUT'])
@jwt_required()
def update_profile():
    """Update user profile"""
    current_user = get_current_user()
    data = request.get_json() or {}
    
    # Update allowed fields
    if 'full_name' in data:
        current_user.full_name = data['full_name'].strip() or None
    if 'theme' in data:
        current_user.theme = data['theme']
    if 'notifications_enabled' in data:
        current_user.notifications_enabled = bool(data['notifications_enabled'])
    
    current_user.updated_at = datetime.utcnow()
    db.session.commit()
    
    log_activity(current_user.id, 'profile_updated')
    
    return jsonify({
        'success': True,
        'message': 'Profile updated',
        'data': {'user': current_user.to_dict()}
    })


@auth_bp.route('/change-password', methods=['POST'])
@jwt_required()
def change_password():
    """Change user password"""
    current_user = get_current_user()
    data = request.get_json() or {}
    
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    
    if not check_password_hash(current_user.password_hash, current_password):
        return jsonify({'success': False, 'message': 'Current password is incorrect'}), 400
    
    valid, msg = validate_password(new_password)
    if not valid:
        return jsonify({'success': False, 'message': msg}), 400
    
    current_user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    
    log_activity(current_user.id, 'password_changed')
    
    return jsonify({'success': True, 'message': 'Password changed successfully'})


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Initiate password reset (placeholder for email integration)"""
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    
    if not email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400
    
    user = User.query.filter_by(email=email).first()
    if not user:
        # Don't reveal if email exists
        return jsonify({'success': True, 'message': 'If the email exists, reset instructions will be sent'})
    
    # TODO: Generate reset token and send email
    log_activity(user.id, 'password_reset_requested')
    
    return jsonify({
        'success': True,
        'message': 'If the email exists, reset instructions will be sent',
        'note': 'Email service not configured. Contact administrator.'
    })


@auth_bp.route('/delete-account', methods=['DELETE'])
@jwt_required()
def delete_account():
    """Delete user account and all associated data"""
    current_user = get_current_user()
    data = request.get_json() or {}
    password = data.get('password', '')
    
    if not check_password_hash(current_user.password_hash, password):
        return jsonify({'success': False, 'message': 'Password is incorrect'}), 400
    
    user_id = current_user.id
    db.session.delete(current_user)
    db.session.commit()
    
    # Activity log entry will be cascade deleted
    
    response = jsonify({'success': True, 'message': 'Account deleted permanently'})
    unset_jwt_cookies(response)
    return response
