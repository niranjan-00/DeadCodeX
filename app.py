"""
DeadCodeX - AI-Powered Dead Code Elimination Tool
Main Flask Application Factory
"""
import os
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from config import config
from extensions import db, jwt, cors, migrate
from models import User, ActivityLog


def create_app(config_name='default'):
    """Application factory pattern for creating Flask app"""
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
        static_url_path='/static'
    )
    
    # Load configuration
    app_config = config.get(config_name, config['default'])
    app.config.from_object(app_config)
    
    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'projects'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'reports'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'backups'), exist_ok=True)
    
    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
    cors.init_app(app, origins=app.config['CORS_ORIGINS'])
    migrate.init_app(app, db)
    
    # JWT error handlers
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({'success': False, 'message': 'Token has expired', 'error': 'token_expired'}), 401
    
    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({'success': False, 'message': 'Invalid token', 'error': 'token_invalid'}), 401
    
    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({'success': False, 'message': 'Authorization required', 'error': 'token_missing'}), 401
    
    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return jsonify({'success': False, 'message': 'Token has been revoked', 'error': 'token_revoked'}), 401
    
    # User loader for JWT
    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        identity = jwt_data["sub"]
        # Convert string identity back to int for DB query
        try:
            user_id = int(identity)
        except (ValueError, TypeError):
            return None
        return User.query.filter_by(id=user_id).first()
    
    # Register blueprints
    from routes.auth import auth_bp
    from routes.upload import upload_bp
    from routes.scan import scan_bp
    from routes.report import report_bp
    from routes.admin import admin_bp
    from routes.main import main_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(upload_bp, url_prefix='/api')
    app.register_blueprint(scan_bp, url_prefix='/api')
    app.register_blueprint(report_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(main_bp)
    
    # Global error handlers
    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'message': 'Endpoint not found', 'error': 'not_found'}), 404
        return render_template('404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'message': 'Internal server error', 'error': 'internal_error'}), 500
        return render_template('500.html'), 500
    
    @app.errorhandler(413)
    def too_large(error):
        return jsonify({'success': False, 'message': 'File too large. Maximum size is 500MB.', 'error': 'file_too_large'}), 413
    
    # Request logging middleware
    @app.before_request
    def log_request():
        if request.path.startswith('/api/'):
            # Skip logging for static and health checks
            pass
    
    # Context processor for global template variables
    @app.context_processor
    def inject_globals():
        return {
            'app_name': app.config['APP_NAME'],
            'app_version': app.config['APP_VERSION'],
            'now': datetime.utcnow()
        }
    
    # Health check endpoint
    @app.route('/api/health')
    def health_check():
        return jsonify({
            'status': 'healthy',
            'service': app.config['APP_NAME'],
            'version': app.config['APP_VERSION'],
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # Create database tables
    with app.app_context():
        db.create_all()
        create_default_admin(app)
    
    return app


def create_default_admin(app):
    """Create default admin user if none exists"""
    from werkzeug.security import generate_password_hash
    
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(
            email=app.config.get('ADMIN_EMAIL', 'admin@deadcodex.dev'),
            username='admin',
            password_hash=generate_password_hash('admin123'),
            full_name='System Administrator',
            role='admin',
            is_active=True
        )
        db.session.add(admin)
        db.session.commit()
        print(f"[INIT] Default admin created: {admin.email} / password: admin123")


# Create app instance for running
app = create_app(os.environ.get('FLASK_ENV', 'development'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
