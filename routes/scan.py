"""
DeadCodeX Scan Routes
Trigger scans, get progress, retrieve results
"""
import os
import time
import threading
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_current_user
from models import Project, ScanResult, Issue, ActivityLog
from extensions import db
from analyzer.scanner import CodeScanner

scan_bp = Blueprint('scan', __name__)

# Store running scan threads
scan_threads = {}


def run_scan_async(scan_id, project_id, scan_options):
    """Run scan in background thread"""
    from app import app
    
    with app.app_context():
        scan = ScanResult.query.get(scan_id)
        if not scan:
            return
        
        try:
            scan.status = 'running'
            scan.progress = 0
            db.session.commit()
            
            project = Project.query.get(project_id)
            if not project or not project.file_path:
                scan.status = 'failed'
                db.session.commit()
                return
            
            # Initialize scanner
            scanner = CodeScanner(project.file_path, options=scan_options, language=project.language)
            
            # Progress callback
            def on_progress(pct):
                scan.progress = int(pct)
                db.session.commit()
            
            scanner.set_progress_callback(on_progress)
            
            # Run analysis
            start_time = time.time()
            results = scanner.scan()
            duration = time.time() - start_time
            
            # Update scan result
            scan.status = 'completed'
            scan.progress = 100
            scan.duration_seconds = round(duration, 2)
            scan.total_files = results.get('total_files', 0)
            scan.total_lines = results.get('total_lines', 0)
            scan.issues_found = len(results.get('issues', []))
            scan.dead_code_lines = results.get('metrics', {}).get('dead_code_lines', 0)
            scan.duplicate_lines = results.get('metrics', {}).get('duplicate_lines', 0)
            scan.security_issues = results.get('metrics', {}).get('security_issues', 0)
            scan.performance_issues = results.get('metrics', {}).get('performance_issues', 0)
            
            # Count severity
            critical = 0
            warning = 0
            info = 0
            for issue in results.get('issues', []):
                sev = issue.get('severity', 'warning')
                if sev == 'critical':
                    critical += 1
                elif sev == 'warning':
                    warning += 1
                else:
                    info += 1
            
            scan.critical_count = critical
            scan.warning_count = warning
            scan.info_count = info
            
            # Calculate health score
            if scan.total_lines > 0:
                issue_ratio = scan.issues_found / max(scan.total_lines / 100, 1)
                scan.health_score = max(0, min(100, int(100 - issue_ratio * 10)))
            scan.confidence_score = results.get('confidence', 0.85)
            
            # Store raw results
            scan.set_results(results)
            db.session.commit()
            
            # Create Issue records
            for issue_data in results.get('issues', []):
                issue = Issue(
                    scan_id=scan.id,
                    issue_type=issue_data.get('type', 'unknown'),
                    severity=issue_data.get('severity', 'warning'),
                    confidence=issue_data.get('confidence', 0.8),
                    file_path=issue_data.get('file', 'unknown'),
                    line_start=issue_data.get('line', 0),
                    title=issue_data.get('title', 'Untitled Issue'),
                    description=issue_data.get('description', ''),
                    code_snippet=issue_data.get('code', ''),
                    suggested_fix=issue_data.get('suggestion', ''),
                    lines_affected=issue_data.get('lines_affected', 1)
                )
                db.session.add(issue)
            
            scan.completed_at = datetime.utcnow() if 'datetime' in globals() else None
            # Fix: import datetime properly
            from datetime import datetime as dt
            scan.completed_at = dt.utcnow()
            db.session.commit()
            
            # Log activity
            log = ActivityLog(
                user_id=scan.user_id,
                action='scan_completed',
                entity_type='scan',
                entity_id=scan.id,
                details=f"Found {scan.issues_found} issues in {project.name}"
            )
            db.session.add(log)
            db.session.commit()
            
        except Exception as e:
            scan.status = 'failed'
            db.session.commit()
            print(f"[SCAN ERROR] Scan {scan_id} failed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if scan_id in scan_threads:
                del scan_threads[scan_id]


@scan_bp.route('/scan', methods=['POST'])
@jwt_required()
def start_scan():
    """Start a new scan on a project"""
    user = get_current_user()
    data = request.get_json() or {}
    
    project_id = data.get('project_id')
    scan_type = data.get('scan_type', 'full')
    scan_options = data.get('options', {})
    
    if not project_id:
        return jsonify({'success': False, 'message': 'Project ID is required'}), 400
    
    project = Project.query.filter_by(id=project_id, user_id=user.id, is_active=True).first()
    if not project:
        return jsonify({'success': False, 'message': 'Project not found'}), 404
    
    # Create scan record
    scan = ScanResult(
        project_id=project.id,
        user_id=user.id,
        scan_type=scan_type,
        status='pending',
        progress=0
    )
    db.session.add(scan)
    db.session.commit()
    
    # Start async scan
    thread = threading.Thread(
        target=run_scan_async,
        args=(scan.id, project.id, scan_options),
        daemon=True
    )
    scan_threads[scan.id] = thread
    thread.start()
    
    # Log activity
    log = ActivityLog(
        user_id=user.id,
        action='scan_started',
        entity_type='scan',
        entity_id=scan.id,
        details=f"Started {scan_type} scan on {project.name}"
    )
    db.session.add(log)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Scan started',
        'data': {
            'scan': scan.to_dict()
        }
    }), 201


@scan_bp.route('/scan/<int:scan_id>/status', methods=['GET'])
@jwt_required()
def get_scan_status(scan_id):
    """Get scan progress and status"""
    user = get_current_user()
    scan = ScanResult.query.filter_by(id=scan_id, user_id=user.id).first()
    
    if not scan:
        return jsonify({'success': False, 'message': 'Scan not found'}), 404
    
    return jsonify({
        'success': True,
        'data': {
            'scan': scan.to_dict()
        }
    })


@scan_bp.route('/scan/<int:scan_id>/results', methods=['GET'])
@jwt_required()
def get_scan_results(scan_id):
    """Get detailed scan results with issues"""
    user = get_current_user()
    scan = ScanResult.query.filter_by(id=scan_id, user_id=user.id).first()
    
    if not scan:
        return jsonify({'success': False, 'message': 'Scan not found'}), 404
    
    issues = Issue.query.filter_by(scan_id=scan.id).all()
    
    return jsonify({
        'success': True,
        'data': {
            'scan': scan.to_dict(),
            'issues': [i.to_dict() for i in issues],
            'summary': scan.get_results().get('summary', {})
        }
    })


@scan_bp.route('/scans', methods=['GET'])
@jwt_required()
def list_scans():
    """List all scans for current user"""
    user = get_current_user()
    project_id = request.args.get('project_id', type=int)
    
    query = ScanResult.query.filter_by(user_id=user.id)
    if project_id:
        query = query.filter_by(project_id=project_id)
    
    scans = query.order_by(ScanResult.created_at.desc()).limit(50).all()
    
    return jsonify({
        'success': True,
        'data': {
            'scans': [s.to_dict() for s in scans],
            'total': len(scans)
        }
    })


@scan_bp.route('/scan/<int:scan_id>', methods=['DELETE'])
@jwt_required()
def delete_scan(scan_id):
    """Delete a scan result"""
    user = get_current_user()
    scan = ScanResult.query.filter_by(id=scan_id, user_id=user.id).first()
    
    if not scan:
        return jsonify({'success': False, 'message': 'Scan not found'}), 404
    
    db.session.delete(scan)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Scan deleted'})
