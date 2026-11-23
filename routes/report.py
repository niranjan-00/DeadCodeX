"""
DeadCodeX Report Routes
Generate and download analysis reports in HTML, PDF, JSON, CSV formats
"""
import os
import json
import csv
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, current_app
from flask_jwt_extended import jwt_required, get_current_user
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from models import ScanResult, Issue, Report, Project, ActivityLog
from extensions import db

report_bp = Blueprint('report', __name__)


@report_bp.route('/report/<int:scan_id>', methods=['GET'])
@jwt_required()
def get_report(scan_id):
    """Get report data for a scan"""
    user = get_current_user()
    scan = ScanResult.query.filter_by(id=scan_id, user_id=user.id).first()
    
    if not scan:
        return jsonify({'success': False, 'message': 'Scan not found'}), 404
    
    issues = Issue.query.filter_by(scan_id=scan.id).all()
    project = Project.query.get(scan.project_id)
    
    # Build report data
    file_issues = {}
    for issue in issues:
        fp = issue.file_path
        if fp not in file_issues:
            file_issues[fp] = []
        file_issues[fp].append(issue.to_dict())
    
    return jsonify({
        'success': True,
        'data': {
            'scan': scan.to_dict(),
            'project': project.to_dict() if project else None,
            'issues': [i.to_dict() for i in issues],
            'file_breakdown': file_issues,
            'severity_distribution': {
                'critical': scan.critical_count,
                'warning': scan.warning_count,
                'info': scan.info_count
            },
            'type_distribution': get_type_distribution(issues)
        }
    })


def get_type_distribution(issues):
    """Group issues by type"""
    dist = {}
    for issue in issues:
        t = issue.issue_type
        dist[t] = dist.get(t, 0) + 1
    return dist


@report_bp.route('/report/<int:scan_id>/export/<string:format>', methods=['GET'])
@jwt_required()
def export_report(scan_id, format):
    """Export report in specified format"""
    user = get_current_user()
    scan = ScanResult.query.filter_by(id=scan_id, user_id=user.id).first()
    
    if not scan:
        return jsonify({'success': False, 'message': 'Scan not found'}), 404
    
    issues = Issue.query.filter_by(scan_id=scan.id).all()
    project = Project.query.get(scan.project_id)
    
    filename_base = f"deadcodex_report_{scan.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    reports_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    
    if format == 'json':
        data = {
            'scan': scan.to_dict(),
            'project': project.to_dict() if project else None,
            'issues': [i.to_dict() for i in issues],
            'generated_at': datetime.now().isoformat()
        }
        filepath = os.path.join(reports_dir, f"{filename_base}.json")
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        return send_file(filepath, as_attachment=True, download_name=f"{filename_base}.json")
    
    elif format == 'csv':
        filepath = os.path.join(reports_dir, f"{filename_base}.csv")
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Type', 'Severity', 'File', 'Line', 'Title', 'Description', 'Suggested Fix', 'Status'])
            for issue in issues:
                writer.writerow([
                    issue.id, issue.issue_type, issue.severity, issue.file_path,
                    issue.line_start, issue.title, issue.description,
                    issue.suggested_fix, issue.status
                ])
        
        return send_file(filepath, as_attachment=True, download_name=f"{filename_base}.csv")
    
    elif format == 'pdf':
        filepath = os.path.join(reports_dir, f"{filename_base}.pdf")
        generate_pdf_report(filepath, scan, project, issues)
        return send_file(filepath, as_attachment=True, download_name=f"{filename_base}.pdf")
    
    else:
        return jsonify({'success': False, 'message': 'Unsupported format. Use json, csv, or pdf'}), 400


def generate_pdf_report(filepath, scan, project, issues):
    """Generate a styled PDF report"""
    doc = SimpleDocTemplate(filepath, pagesize=letter,
                            rightMargin=72, leftMargin=72,
                            topMargin=72, bottomMargin=18)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#6366f1'),
        spaceAfter=30
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#4f46e5'),
        spaceAfter=12
    )
    
    story = []
    
    # Title
    story.append(Paragraph("DeadCodeX Analysis Report", title_style))
    story.append(Spacer(1, 12))
    
    # Meta info
    story.append(Paragraph(f"<b>Project:</b> {project.name if project else 'Unknown'}", styles['Normal']))
    story.append(Paragraph(f"<b>Scan Type:</b> {scan.scan_type}", styles['Normal']))
    story.append(Paragraph(f"<b>Date:</b> {scan.created_at.strftime('%Y-%m-%d %H:%M') if scan.created_at else 'N/A'}", styles['Normal']))
    story.append(Paragraph(f"<b>Health Score:</b> {scan.health_score}/100", styles['Normal']))
    story.append(Paragraph(f"<b>Issues Found:</b> {scan.issues_found} ({scan.critical_count} critical, {scan.warning_count} warnings, {scan.info_count} info)", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Severity table
    story.append(Paragraph("Severity Summary", heading_style))
    severity_data = [
        ['Severity', 'Count', 'Percentage'],
        ['Critical', str(scan.critical_count), f"{scan.critical_count / max(scan.issues_found, 1) * 100:.1f}%"],
        ['Warning', str(scan.warning_count), f"{scan.warning_count / max(scan.issues_found, 1) * 100:.1f}%"],
        ['Info', str(scan.info_count), f"{scan.info_count / max(scan.issues_found, 1) * 100:.1f}%"],
    ]
    sev_table = Table(severity_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
    sev_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4f46e5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
    ]))
    story.append(sev_table)
    story.append(Spacer(1, 20))
    
    # Issues list
    if issues:
        story.append(PageBreak())
        story.append(Paragraph("Detailed Issues", heading_style))
        
        for issue in issues[:100]:  # Limit to first 100 for PDF size
            story.append(Paragraph(f"<b>{issue.title}</b>", styles['Heading3']))
            story.append(Paragraph(f"<b>File:</b> {issue.file_path}:{issue.line_start}", styles['Normal']))
            story.append(Paragraph(f"<b>Type:</b> {issue.issue_type} | <b>Severity:</b> {issue.severity} | <b>Confidence:</b> {issue.confidence:.0%}", styles['Normal']))
            if issue.description:
                story.append(Paragraph(f"<b>Description:</b> {issue.description}", styles['Normal']))
            if issue.suggested_fix:
                story.append(Paragraph(f"<b>Suggested Fix:</b> {issue.suggested_fix}", styles['Normal']))
            story.append(Spacer(1, 12))
    
    doc.build(story)


@report_bp.route('/report/<int:scan_id>/cleanup-preview', methods=['GET'])
@jwt_required()
def cleanup_preview(scan_id):
    """Preview what cleanup would do"""
    user = get_current_user()
    scan = ScanResult.query.filter_by(id=scan_id, user_id=user.id).first()
    
    if not scan:
        return jsonify({'success': False, 'message': 'Scan not found'}), 404
    
    issues = Issue.query.filter_by(scan_id=scan.id, status='open').all()
    
    # Calculate cleanup impact
    files_affected = set()
    total_lines_saved = 0
    fixable_issues = []
    
    for issue in issues:
        if issue.issue_type in ['unused_import', 'unused_variable', 'dead_code', 'empty_block', 'duplicate_code']:
            fixable_issues.append(issue.to_dict())
            files_affected.add(issue.file_path)
            total_lines_saved += issue.lines_affected
    
    return jsonify({
        'success': True,
        'data': {
            'scan_id': scan_id,
            'files_affected': list(files_affected),
            'files_count': len(files_affected),
            'issues_fixable': len(fixable_issues),
            'total_lines_saved': total_lines_saved,
            'estimated_size_saved': total_lines_saved * 40,  # Rough estimate: 40 bytes/line
            'fixable_issues': fixable_issues[:50]
        }
    })
