"""
DeadCodeX Admin Routes
Admin panel APIs: user management, system stats, usage analytics
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_current_user
from sqlalchemy import func
from models import User, Project, ScanResult, Issue, ActivityLog
from extensions import db

admin_bp = Blueprint('admin', __name__)


def admin_required(fn):
    """Decorator to require admin role"""
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or not user.is_admin():
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


@admin_bp.route('/stats', methods=['GET'])
@jwt_required()
@admin_required
def get_system_stats():
    """Get system-wide statistics"""
    # User stats
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    admin_users = User.query.filter_by(role='admin').count()
    new_users_today = User.query.filter(
        func.date(User.created_at) == func.date('now')
    ).count()
    
    # Project stats
    total_projects = Project.query.count()
    active_projects = Project.query.filter_by(is_active=True).count()
    
    # Scan stats
    total_scans = ScanResult.query.count()
    completed_scans = ScanResult.query.filter_by(status='completed').count()
    failed_scans = ScanResult.query.filter_by(status='failed').count()
    total_issues = Issue.query.count()
    
    # Issue severity breakdown
    critical_issues = Issue.query.filter_by(severity='critical').count()
    warning_issues = Issue.query.filter_by(severity='warning').count()
    info_issues = Issue.query.filter_by(severity='info').count()
    
    # Recent activity
    recent_activity = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(20).all()
    
    return jsonify({
        'success': True,
        'data': {
            'users': {
                'total': total_users,
                'active': active_users,
                'admins': admin_users,
                'new_today': new_users_today
            },
            'projects': {
                'total': total_projects,
                'active': active_projects
            },
            'scans': {
                'total': total_scans,
                'completed': completed_scans,
                'failed': failed_scans,
                'success_rate': round(completed_scans / max(total_scans, 1) * 100, 1)
            },
            'issues': {
                'total': total_issues,
                'critical': critical_issues,
                'warning': warning_issues,
                'info': info_issues
            },
            'recent_activity': [a.to_dict() for a in recent_activity]
        }
    })


@admin_bp.route('/users', methods=['GET'])
@jwt_required()
@admin_required
def list_all_users():
    """List all users (admin only)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()
    
    query = User.query
    if search:
        query = query.filter(
            db.or_(
                User.email.contains(search),
                User.username.contains(search),
                User.full_name.contains(search)
            )
        )
    
    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'success': True,
        'data': {
            'users': [u.to_dict() for u in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page,
            'per_page': per_page
        }
    })


@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@jwt_required()
@admin_required
def get_user_detail(user_id):
    """Get detailed user information"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    projects = Project.query.filter_by(user_id=user.id).all()
    scans = ScanResult.query.filter_by(user_id=user.id).order_by(ScanResult.created_at.desc()).limit(10).all()
    activity = ActivityLog.query.filter_by(user_id=user.id).order_by(ActivityLog.created_at.desc()).limit(20).all()
    
    return jsonify({
        'success': True,
        'data': {
            'user': user.to_dict(),
            'projects': [p.to_dict() for p in projects],
            'recent_scans': [s.to_dict() for s in scans],
            'recent_activity': [a.to_dict() for a in activity]
        }
    })


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@jwt_required()
@admin_required
def toggle_user_status(user_id):
    """Activate/deactivate a user"""
    target_user = User.query.get(user_id)
    if not target_user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    target_user.is_active = not target_user.is_active
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f"User {'activated' if target_user.is_active else 'deactivated'}",
        'data': {'user': target_user.to_dict()}
    })


@admin_bp.route('/users/<int:user_id>/role', methods=['PUT'])
@jwt_required()
@admin_required
def update_user_role(user_id):
    """Change user role"""
    data = request.get_json() or {}
    role = data.get('role', 'user')
    
    if role not in ['user', 'admin']:
        return jsonify({'success': False, 'message': 'Invalid role'}), 400
    
    target_user = User.query.get(user_id)
    if not target_user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    target_user.role = role
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f"Role updated to {role}",
        'data': {'user': target_user.to_dict()}
    })


@admin_bp.route('/scans/monitor', methods=['GET'])
@jwt_required()
@admin_required
def monitor_scans():
    """Monitor scan activity"""
    status = request.args.get('status', None)
    
    query = ScanResult.query
    if status:
        query = query.filter_by(status=status)
    
    scans = query.order_by(ScanResult.created_at.desc()).limit(50).all()
    
    return jsonify({
        'success': True,
        'data': {
            'scans': [s.to_dict() for s in scans],
            'running_count': ScanResult.query.filter_by(status='running').count(),
            'pending_count': ScanResult.query.filter_by(status='pending').count(),
            'failed_count': ScanResult.query.filter_by(status='failed').count()
        }
    })


@admin_bp.route('/analytics/usage', methods=['GET'])
@jwt_required()
@admin_required
def usage_analytics():
    """Get usage analytics"""
    # Scans per day (last 30 days)
    from sqlalchemy import func, extract
    from datetime import datetime, timedelta
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    daily_scans = db.session.query(
        func.date(ScanResult.created_at).label('date'),
        func.count(ScanResult.id).label('count')
    ).filter(ScanResult.created_at >= thirty_days_ago).group_by(
        func.date(ScanResult.created_at)
    ).all()
    
    daily_users = db.session.query(
        func.date(ActivityLog.created_at).label('date'),
        func.count(db.distinct(ActivityLog.user_id)).label('count')
    ).filter(ActivityLog.created_at >= thirty_days_ago).group_by(
        func.date(ActivityLog.created_at)
    ).all()
    
    return jsonify({
        'success': True,
        'data': {
            'daily_scans': [{'date': str(d.date), 'count': d.count} for d in daily_scans],
            'daily_active_users': [{'date': str(d.date), 'count': d.count} for d in daily_users],
            'total_projects_all_time': Project.query.count(),
            'total_scans_all_time': ScanResult.query.count()
        }
    })
