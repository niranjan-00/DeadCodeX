"""
DeadCodeX Database Models
SQLAlchemy ORM models for users, projects, scans, issues, and reports
"""
from datetime import datetime
from extensions import db
import json


class User(db.Model):
    """User model with role-based access"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    avatar = db.Column(db.String(256), nullable=True)
    role = db.Column(db.String(20), default='user')  # 'user' or 'admin'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # Settings
    theme = db.Column(db.String(20), default='dark')
    notifications_enabled = db.Column(db.Boolean, default=True)
    api_key = db.Column(db.String(256), nullable=True)
    
    # Relationships
    projects = db.relationship('Project', backref='owner', lazy='dynamic', cascade='all, delete-orphan')
    scans = db.relationship('ScanResult', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    activities = db.relationship('ActivityLog', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'username': self.username,
            'full_name': self.full_name,
            'avatar': self.avatar,
            'role': self.role,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'theme': self.theme,
            'notifications_enabled': self.notifications_enabled,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'project_count': self.projects.count(),
            'scan_count': self.scans.count()
        }
    
    def is_admin(self):
        return self.role == 'admin'


class Project(db.Model):
    """Project model for uploaded repositories"""
    __tablename__ = 'projects'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    source_type = db.Column(db.String(50), default='upload')  # 'upload', 'github', 'manual'
    source_url = db.Column(db.String(500), nullable=True)
    file_path = db.Column(db.String(500), nullable=True)
    language = db.Column(db.String(50), default='python')
    total_files = db.Column(db.Integer, default=0)
    total_lines = db.Column(db.Integer, default=0)
    size_bytes = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    scans = db.relationship('ScanResult', backref='project', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'source_type': self.source_type,
            'source_url': self.source_url,
            'language': self.language,
            'total_files': self.total_files,
            'total_lines': self.total_lines,
            'size_bytes': self.size_bytes,
            'user_id': self.user_id,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'scan_count': self.scans.count()
        }


class ScanResult(db.Model):
    """Scan result model storing analysis results"""
    __tablename__ = 'scan_results'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Scan metadata
    scan_type = db.Column(db.String(100), default='full')  # 'full', 'dead_code', 'security', 'duplicate', 'performance'
    status = db.Column(db.String(50), default='pending')  # 'pending', 'running', 'completed', 'failed'
    progress = db.Column(db.Integer, default=0)  # 0-100
    
    # Statistics
    total_files = db.Column(db.Integer, default=0)
    total_lines = db.Column(db.Integer, default=0)
    issues_found = db.Column(db.Integer, default=0)
    critical_count = db.Column(db.Integer, default=0)
    warning_count = db.Column(db.Integer, default=0)
    info_count = db.Column(db.Integer, default=0)
    
    # Code metrics
    dead_code_lines = db.Column(db.Integer, default=0)
    duplicate_lines = db.Column(db.Integer, default=0)
    security_issues = db.Column(db.Integer, default=0)
    performance_issues = db.Column(db.Integer, default=0)
    
    # Scores
    health_score = db.Column(db.Integer, default=100)  # 0-100
    confidence_score = db.Column(db.Float, default=0.0)  # 0.0-1.0
    
    # Raw results (JSON)
    results_json = db.Column(db.Text, nullable=True)
    
    # Duration in seconds
    duration_seconds = db.Column(db.Float, default=0.0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    issues = db.relationship('Issue', backref='scan', lazy='dynamic', cascade='all, delete-orphan')
    report = db.relationship('Report', backref='scan', uselist=False, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'project_name': self.project.name if self.project else None,
            'user_id': self.user_id,
            'scan_type': self.scan_type,
            'status': self.status,
            'progress': self.progress,
            'total_files': self.total_files,
            'total_lines': self.total_lines,
            'issues_found': self.issues_found,
            'critical_count': self.critical_count,
            'warning_count': self.warning_count,
            'info_count': self.info_count,
            'dead_code_lines': self.dead_code_lines,
            'duplicate_lines': self.duplicate_lines,
            'security_issues': self.security_issues,
            'performance_issues': self.performance_issues,
            'health_score': self.health_score,
            'confidence_score': self.confidence_score,
            'duration_seconds': self.duration_seconds,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }
    
    def get_results(self):
        """Parse JSON results"""
        if self.results_json:
            try:
                return json.loads(self.results_json)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def set_results(self, data):
        """Serialize results to JSON"""
        self.results_json = json.dumps(data, default=str)


class Issue(db.Model):
    """Individual issue found during scan"""
    __tablename__ = 'issues'
    
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scan_results.id'), nullable=False)
    
    # Issue details
    issue_type = db.Column(db.String(100), nullable=False)  # 'unused_variable', 'unused_function', 'dead_code', 'duplicate', 'security', 'performance', etc.
    severity = db.Column(db.String(20), default='warning')  # 'critical', 'warning', 'info'
    confidence = db.Column(db.Float, default=0.8)  # 0.0-1.0
    
    # Location
    file_path = db.Column(db.String(500), nullable=False)
    line_start = db.Column(db.Integer, default=0)
    line_end = db.Column(db.Integer, default=0)
    column_start = db.Column(db.Integer, default=0)
    column_end = db.Column(db.Integer, default=0)
    
    # Content
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    code_snippet = db.Column(db.Text, nullable=True)
    suggested_fix = db.Column(db.Text, nullable=True)
    
    # Metrics
    lines_affected = db.Column(db.Integer, default=1)
    
    # Status
    status = db.Column(db.String(50), default='open')  # 'open', 'fixed', 'ignored', 'false_positive'
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'scan_id': self.scan_id,
            'issue_type': self.issue_type,
            'severity': self.severity,
            'confidence': self.confidence,
            'file_path': self.file_path,
            'line_start': self.line_start,
            'line_end': self.line_end,
            'title': self.title,
            'description': self.description,
            'code_snippet': self.code_snippet,
            'suggested_fix': self.suggested_fix,
            'lines_affected': self.lines_affected,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Report(db.Model):
    """Generated report model"""
    __tablename__ = 'reports'
    
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scan_results.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Report metadata
    report_type = db.Column(db.String(50), default='full')  # 'full', 'summary', 'security', 'performance'
    format = db.Column(db.String(20), default='html')  # 'html', 'pdf', 'json', 'csv'
    
    # File path
    file_path = db.Column(db.String(500), nullable=True)
    file_size = db.Column(db.Integer, default=0)
    
    # Content
    summary = db.Column(db.Text, nullable=True)
    recommendations = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    downloaded_at = db.Column(db.DateTime, nullable=True)
    download_count = db.Column(db.Integer, default=0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'scan_id': self.scan_id,
            'user_id': self.user_id,
            'report_type': self.report_type,
            'format': self.format,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'summary': self.summary,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'download_count': self.download_count
        }


class ActivityLog(db.Model):
    """User activity tracking"""
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=True)  # 'project', 'scan', 'report', 'user'
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'details': self.details,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class CleanupJob(db.Model):
    """Cleanup operation tracking"""
    __tablename__ = 'cleanup_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scan_results.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Job details
    status = db.Column(db.String(50), default='pending')  # 'pending', 'running', 'completed', 'failed', 'restored'
    files_modified = db.Column(db.Integer, default=0)
    lines_removed = db.Column(db.Integer, default=0)
    issues_fixed = db.Column(db.Integer, default=0)
    
    # Backup
    backup_path = db.Column(db.String(500), nullable=True)
    cleaned_path = db.Column(db.String(500), nullable=True)
    
    # Changes tracking
    changes_json = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'scan_id': self.scan_id,
            'user_id': self.user_id,
            'status': self.status,
            'files_modified': self.files_modified,
            'lines_removed': self.lines_removed,
            'issues_fixed': self.issues_fixed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }
