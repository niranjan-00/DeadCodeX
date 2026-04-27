"""
DeadCodeX Static Code Analyzer - Scanner
Main scanning engine that orchestrates all analysis modules
"""
import os
import re
import ast
import hashlib
from typing import Dict, List, Callable, Optional


class CodeScanner:
    """
    Main scanner class that coordinates multiple analysis engines
    to detect dead code, security issues, duplicates, and more.
    """
    
    SUPPORTED_LANGUAGES = {
        'python': ['py'],
        'javascript': ['js', 'jsx', 'mjs'],
        'typescript': ['ts', 'tsx'],
        'java': ['java'],
        'cpp': ['cpp', 'cc', 'cxx', 'hpp'],
        'c': ['c', 'h'],
        'csharp': ['cs'],
        'php': ['php'],
        'ruby': ['rb'],
        'go': ['go'],
        'rust': ['rs'],
        'swift': ['swift'],
        'kotlin': ['kt', 'kts'],
        'html': ['html', 'htm'],
        'css': ['css', 'scss', 'sass', 'less'],
        'json': ['json'],
        'yaml': ['yaml', 'yml'],
        'xml': ['xml'],
    }
    
    def __init__(self, project_path: str, options: Optional[Dict] = None, language: str = 'python'):
        self.project_path = project_path
        self.options = options or {}
        self.language = language
        self.progress_callback: Optional[Callable[[float], None]] = None
        
        self.files = []
        self.issues: List[Dict] = []
        self.metrics = {
            'total_files': 0,
            'total_lines': 0,
            'dead_code_lines': 0,
            'duplicate_lines': 0,
            'security_issues': 0,
            'performance_issues': 0
        }
        
        self._file_hashes = {}  # For duplicate detection
        self._file_contents = {}  # Cache file contents
    
    def set_progress_callback(self, callback: Callable[[float], None]):
        self.progress_callback = callback
    
    def _update_progress(self, pct: float):
        if self.progress_callback:
            self.progress_callback(min(100, max(0, pct)))
    
    def _get_extensions(self) -> List[str]:
        """Get file extensions for the target language"""
        exts = self.SUPPORTED_LANGUAGES.get(self.language, [])
        if self.options.get('scan_all_languages', False):
            all_exts = []
            for e in self.SUPPORTED_LANGUAGES.values():
                all_exts.extend(e)
            exts = list(set(all_exts))
        return exts
    
    def _collect_files(self):
        """Collect all source files from project"""
        extensions = self._get_extensions()
        skip_dirs = {
            'node_modules', '__pycache__', 'venv', '.git', 'dist', 
            'build', 'vendor', '.idea', '.vscode', 'target', 'bin', 
            'obj', 'out', 'coverage', '.pytest_cache', '.mypy_cache',
            'site-packages', 'egg-info', '.eggs'
        }
        skip_files = {'package-lock.json', 'yarn.lock', 'Pipfile.lock'}
        
        collected = []
        for root, dirs, files in os.walk(self.project_path):
            # Skip hidden and dependency directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in skip_dirs]
            
            for filename in files:
                if filename.startswith('.') or filename in skip_files:
                    continue
                
                # Check extension
                ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
                if extensions and ext not in extensions:
                    continue
                
                filepath = os.path.join(root, filename)
                try:
                    size = os.path.getsize(filepath)
                    if size > 10 * 1024 * 1024:  # Skip files > 10MB
                        continue
                    collected.append(filepath)
                except OSError:
                    continue
        
        self.files = collected
        self.metrics['total_files'] = len(collected)
        return collected
    
    def _read_file(self, filepath: str) -> str:
        """Read file contents with caching"""
        if filepath in self._file_contents:
            return self._file_contents[filepath]
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            self._file_contents[filepath] = content
            self.metrics['total_lines'] += content.count('\n') + 1
            return content
        except Exception:
            return ''
    
    def scan(self) -> Dict:
        """
        Run the complete scan and return results.
        """
        # Phase 1: Collect files
        self._collect_files()
        self._update_progress(5)
        
        # Phase 2: Run analyzers based on options
        analyzers = []
        
        if self.options.get('dead_code', True):
            analyzers.append(self._analyze_dead_code)
        
        if self.options.get('security', True):
            analyzers.append(self._analyze_security)
        
        if self.options.get('duplicates', True):
            analyzers.append(self._analyze_duplicates)
        
        if self.options.get('performance', False):
            analyzers.append(self._analyze_performance)
        
        if self.options.get('quality', True):
            analyzers.append(self._analyze_quality)
        
        if not analyzers:
            analyzers = [self._analyze_dead_code, self._analyze_security, 
                        self._analyze_duplicates, self._analyze_quality]
        
        # Run each analyzer
        total = len(analyzers)
        for idx, analyzer in enumerate(analyzers):
            try:
                analyzer()
            except Exception as e:
                self.issues.append({
                    'type': 'scan_error',
                    'severity': 'info',
                    'title': f'Scanner Error: {analyzer.__name__}',
                    'description': str(e),
                    'file': 'system',
                    'line': 0,
                    'confidence': 1.0
                })
            self._update_progress(5 + (idx + 1) / total * 90)
        
        self._update_progress(100)
        
        # Build summary
        summary = self._build_summary()
        
        return {
            'total_files': self.metrics['total_files'],
            'total_lines': self.metrics['total_lines'],
            'issues_found': len(self.issues),
            'metrics': self.metrics,
            'issues': self.issues,
            'summary': summary,
            'confidence': self._calculate_confidence(),
            'language': self.language
        }
    
    def _build_summary(self) -> Dict:
        """Build scan summary"""
        severity_count = {'critical': 0, 'warning': 0, 'info': 0}
        type_count = {}
        
        for issue in self.issues:
            sev = issue.get('severity', 'warning')
            severity_count[sev] = severity_count.get(sev, 0) + 1
            
            itype = issue.get('type', 'unknown')
            type_count[itype] = type_count.get(itype, 0) + 1
        
        return {
            'severity_distribution': severity_count,
            'type_distribution': type_count,
            'files_scanned': self.metrics['total_files'],
            'total_lines': self.metrics['total_lines'],
            'estimated_lines_saved': self.metrics['dead_code_lines'] + self.metrics['duplicate_lines']
        }
    
    def _calculate_confidence(self) -> float:
        """Calculate overall confidence score based on issues"""
        if not self.issues:
            return 1.0
        
        confidences = [i.get('confidence', 0.8) for i in self.issues]
        return round(sum(confidences) / len(confidences), 2)
    
    # ============== ANALYZER MODULES ==============
    
    def _analyze_dead_code(self):
        """Detect dead code: unused variables, functions, imports, unreachable code"""
        from analyzer.ast_engine import PythonASTAnalyzer
        from analyzer.rules import RegexRuleEngine
        
        regex_engine = RegexRuleEngine()
        
        for idx, filepath in enumerate(self.files):
            content = self._read_file(filepath)
            if not content:
                continue
            
            rel_path = os.path.relpath(filepath, self.project_path)
            lines = content.split('\n')
            
            # Python AST analysis
            if self.language == 'python' and filepath.endswith('.py'):
                try:
                    ast_analyzer = PythonASTAnalyzer(content, filepath)
                    ast_issues = ast_analyzer.analyze()
                    for issue in ast_issues:
                        issue['file'] = rel_path
                        self.issues.append(issue)
                        if issue.get('type') in ('unused_import', 'unused_variable', 'dead_code'):
                            self.metrics['dead_code_lines'] += issue.get('lines_affected', 1)
                except SyntaxError:
                    pass  # Skip files with syntax errors
                except Exception:
                    pass
            
            # Regex-based rules for all languages
            regex_issues = regex_engine.check_file(rel_path, content, self.language)
            for issue in regex_issues:
                self.issues.append(issue)
                if issue.get('type') in ('unused_import', 'unused_variable', 'dead_code', 'empty_block', 'commented_code'):
                    self.metrics['dead_code_lines'] += issue.get('lines_affected', 1)
            
            # Detect commented-out code blocks
            self._detect_commented_code(rel_path, lines)
            
            # Detect empty blocks
            self._detect_empty_blocks(rel_path, content, lines)
            
            # Detect unreachable code patterns
            self._detect_unreachable_patterns(rel_path, content, lines)
    
    def _analyze_security(self):
        """Detect security smells and vulnerabilities"""
        security_patterns = [
            (r'password\s*=\s*["\'][^"\']+["\']', 'hardcoded_password', 'Hardcoded password detected', 'critical'),
            (r'secret\s*=\s*["\'][^"\']+["\']', 'hardcoded_secret', 'Hardcoded secret detected', 'critical'),
            (r'api[_-]?key\s*=\s*["\'][^"\']+["\']', 'hardcoded_api_key', 'Hardcoded API key detected', 'critical'),
            (r'token\s*=\s*["\'][^"\']+["\']', 'hardcoded_token', 'Hardcoded token detected', 'critical'),
            (r'eval\s*\(', 'dangerous_eval', 'Use of eval() is dangerous', 'critical'),
            (r'exec\s*\(', 'dangerous_exec', 'Use of exec() is dangerous', 'critical'),
            (r'subprocess\.call\s*\([^)]*shell\s*=\s*True', 'shell_injection', 'Shell=True can lead to command injection', 'critical'),
            (r'\.format\s*\([^)]*\)', 'potential_format_injection', 'String format with potential injection', 'warning'),
            (r'innerHTML\s*=', 'xss_innerHTML', 'innerHTML assignment can lead to XSS', 'warning'),
            (r'document\.write\s*\(', 'xss_document_write', 'document.write can lead to XSS', 'warning'),
            (r'http://', 'insecure_http', 'Insecure HTTP connection', 'warning'),
            (r'verify\s*=\s*False', 'ssl_verify_disabled', 'SSL verification disabled', 'warning'),
            (r'pickle\.(loads|load)\s*\(', 'insecure_deserialization', 'Insecure deserialization with pickle', 'critical'),
            (r'yaml\.load\s*\([^)]*(?!Loader|SafeLoader)', 'yaml_insecure_load', 'Insecure YAML loading', 'critical'),
            (r'random\.', 'insecure_random', 'random is not cryptographically secure', 'info'),
            (r'MD5|md5', 'weak_hash_md5', 'MD5 is a weak hashing algorithm', 'warning'),
            (r'SHA1|sha1', 'weak_hash_sha1', 'SHA1 is a weak hashing algorithm', 'warning'),
            (r'DEBUG\s*=\s*True', 'debug_enabled', 'Debug mode enabled in production code', 'warning'),
        ]
        
        for filepath in self.files:
            content = self._read_file(filepath)
            if not content:
                continue
            
            rel_path = os.path.relpath(filepath, self.project_path)
            lines = content.split('\n')
            
            for pattern, issue_type, title, severity in security_patterns:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    line_num = content[:match.start()].count('\n') + 1
                    
                    # Skip false positives in comments
                    line = lines[line_num - 1] if line_num <= len(lines) else ''
                    stripped = line.strip()
                    if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('*'):
                        continue
                    
                    self.issues.append({
                        'type': issue_type,
                        'severity': severity,
                        'title': title,
                        'description': f"Pattern matched: {pattern}",
                        'file': rel_path,
                        'line': line_num,
                        'code': line[:100],
                        'suggestion': 'Remove or secure this sensitive code',
                        'confidence': 0.9,
                        'lines_affected': 1
                    })
                    self.metrics['security_issues'] += 1
    
    def _analyze_duplicates(self):
        """Detect duplicate code blocks across files"""
        # Build hash map of code blocks (5-line sliding window)
        block_map = {}  # hash -> [(filepath, line_num), ...]
        
        for filepath in self.files:
            content = self._read_file(filepath)
            if not content:
                continue
            
            rel_path = os.path.relpath(filepath, self.project_path)
            lines = content.split('\n')
            
            # Use 5-line blocks
            for i in range(len(lines) - 4):
                # Skip empty or short blocks
                block = '\n'.join(lines[i:i+5])
                stripped = block.strip()
                if len(stripped) < 30:
                    continue
                if stripped.startswith(('#', '//', '*', '/*', '*/')):
                    continue
                
                # Normalize and hash
                normalized = re.sub(r'\s+', ' ', stripped)
                block_hash = hashlib.md5(normalized.encode()).hexdigest()
                
                if block_hash not in block_map:
                    block_map[block_hash] = []
                block_map[block_hash].append((rel_path, i + 1, block))
        
        # Report duplicates found in 2+ files or 3+ times in same file
        for block_hash, occurrences in block_map.items():
            if len(occurrences) >= 3:
                # Check if they're in different locations
                unique_locations = set((fp, ln) for fp, ln, _ in occurrences)
                if len(unique_locations) >= 2:
                    files_involved = list(set(fp for fp, _, _ in occurrences))
                    first_file, first_line, first_block = occurrences[0]
                    
                    self.issues.append({
                        'type': 'duplicate_code',
                        'severity': 'warning',
                        'title': f'Duplicate code block found {len(occurrences)} times',
                        'description': f"Identical code found in {len(files_involved)} file(s)",
                        'file': first_file,
                        'line': first_line,
                        'code': first_block[:200],
                        'suggestion': 'Extract into a shared function or constant',
                        'confidence': 0.85,
                        'lines_affected': 5,
                        'files_involved': files_involved
                    })
                    self.metrics['duplicate_lines'] += 5
    
    def _analyze_performance(self):
        """Detect performance issues"""
        perf_patterns = [
            (r'for\s+\w+\s+in\s+range\s*\(\s*len\s*\(', 'inefficient_loop', 'Using range(len()) is inefficient', 'warning'),
            (r'\.append\s*\(\s*\)\s*inside\s+loop', 'list_append_loop', 'List append in loop - consider list comprehension', 'info'),
            (r'sql\s*=\s*["\']SELECT\s+\*', 'select_star', 'SELECT * can hurt performance', 'warning'),
            (r'N\+1', 'n_plus_one', 'Potential N+1 query problem', 'warning'),
            (r'recursive', 'deep_recursion', 'Recursive function may cause stack overflow', 'info'),
            (r'sleep\s*\(', 'blocking_sleep', 'Blocking sleep in async context', 'warning'),
        ]
        
        for filepath in self.files:
            content = self._read_file(filepath)
            if not content:
                continue
            
            rel_path = os.path.relpath(filepath, self.project_path)
            lines = content.split('\n')
            
            for pattern, issue_type, title, severity in perf_patterns:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    line_num = content[:match.start()].count('\n') + 1
                    self.issues.append({
                        'type': issue_type,
                        'severity': severity,
                        'title': title,
                        'description': f"Performance pattern matched",
                        'file': rel_path,
                        'line': line_num,
                        'code': lines[line_num - 1][:100] if line_num <= len(lines) else '',
                        'suggestion': 'Optimize this code block',
                        'confidence': 0.7,
                        'lines_affected': 1
                    })
                    self.metrics['performance_issues'] += 1
    
    def _analyze_quality(self):
        """Detect code quality issues: naming, large files, complexity"""
        for filepath in self.files:
            content = self._read_file(filepath)
            if not content:
                continue
            
            rel_path = os.path.relpath(filepath, self.project_path)
            lines = content.split('\n')
            line_count = len(lines)
            
            # Large file detection
            if line_count > 500:
                self.issues.append({
                    'type': 'large_file',
                    'severity': 'warning',
                    'title': f'Large file: {line_count} lines',
                    'description': f"This file has {line_count} lines. Consider breaking it into smaller modules.",
                    'file': rel_path,
                    'line': 1,
                    'code': f'# File: {rel_path} ({line_count} lines)',
                    'suggestion': 'Split into multiple files or classes',
                    'confidence': 0.95,
                    'lines_affected': line_count
                })
            
            # Very large file
            if line_count > 1000:
                self.issues.append({
                    'type': 'very_large_file',
                    'severity': 'critical',
                    'title': f'Very large file: {line_count} lines',
                    'description': f"This file is extremely large ({line_count} lines). Refactor immediately.",
                    'file': rel_path,
                    'line': 1,
                    'code': f'# File: {rel_path} ({line_count} lines)',
                    'suggestion': 'Urgent: Split this file into multiple modules',
                    'confidence': 0.95,
                    'lines_affected': line_count
                })
            
            # TODO/FIXME tracking
            for idx, line in enumerate(lines):
                if re.search(r'\b(TODO|FIXME|HACK|XXX|BUG)\b', line, re.IGNORECASE):
                    self.issues.append({
                        'type': 'todo_item',
                        'severity': 'info',
                        'title': f"{re.search(r'(TODO|FIXME|HACK|XXX|BUG)', line, re.IGNORECASE).group(1)} found",
                        'description': f"Pending task: {line.strip()[:100]}",
                        'file': rel_path,
                        'line': idx + 1,
                        'code': line[:100],
                        'suggestion': 'Resolve this pending item',
                        'confidence': 0.95,
                        'lines_affected': 1
                    })
            
            # Long lines
            for idx, line in enumerate(lines):
                if len(line) > 120:
                    self.issues.append({
                        'type': 'long_line',
                        'severity': 'info',
                        'title': f'Line too long ({len(line)} chars)',
                        'description': f"Line exceeds 120 characters",
                        'file': rel_path,
                        'line': idx + 1,
                        'code': line[:80] + '...',
                        'suggestion': 'Break into multiple lines or use variables',
                        'confidence': 0.9,
                        'lines_affected': 1
                    })
    
    def _detect_commented_code(self, rel_path: str, lines: List[str]):
        """Detect blocks of commented-out code"""
        comment_block = []
        block_start = 0
        
        for idx, line in enumerate(lines):
            stripped = line.strip()
            
            # Detect commented lines that look like code
            is_commented = False
            code_part = stripped
            
            if stripped.startswith('#'):
                is_commented = True
                code_part = stripped[1:].strip()
            elif stripped.startswith('//'):
                is_commented = True
                code_part = stripped[2:].strip()
            
            if is_commented and self._looks_like_code(code_part):
                if not comment_block:
                    block_start = idx + 1
                comment_block.append(code_part)
            else:
                if len(comment_block) >= 3:  # At least 3 lines
                    self.issues.append({
                        'type': 'commented_code',
                        'severity': 'warning',
                        'title': f'Commented-out code block ({len(comment_block)} lines)',
                        'description': f"{len(comment_block)} lines of commented code detected. Remove if no longer needed.",
                        'file': rel_path,
                        'line': block_start,
                        'code': '\n'.join(comment_block[:5]),
                        'suggestion': 'Delete commented code or restore if needed',
                        'confidence': 0.8,
                        'lines_affected': len(comment_block)
                    })
                    self.metrics['dead_code_lines'] += len(comment_block)
                comment_block = []
        
        # Check remaining block at EOF
        if len(comment_block) >= 3:
            self.issues.append({
                'type': 'commented_code',
                'severity': 'warning',
                'title': f'Commented-out code block ({len(comment_block)} lines)',
                'description': f"{len(comment_block)} lines of commented code detected",
                'file': rel_path,
                'line': block_start,
                'code': '\n'.join(comment_block[:5]),
                'suggestion': 'Delete commented code or restore if needed',
                'confidence': 0.8,
                'lines_affected': len(comment_block)
            })
            self.metrics['dead_code_lines'] += len(comment_block)
    
    def _looks_like_code(self, text: str) -> bool:
        """Check if text looks like actual code rather than a comment"""
        code_indicators = [
            r'^(def|class|function|if|for|while|return|import|from|var|let|const)\b',
            r'[=+\-*/<>{}\[\]()]',
            r'^[\s]*(print|console|log|echo)\b',
            r';$',
        ]
        
        for pattern in code_indicators:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        
        return len(text) > 10 and not text.endswith('.') and not text.endswith('?')
    
    def _detect_empty_blocks(self, rel_path: str, content: str, lines: List[str]):
        """Detect empty code blocks"""
        # Python: empty functions/classes
        empty_patterns = [
            (r'def\s+\w+\s*\([^)]*\)\s*:\s*\n\s*pass\b', 'empty_function', 'Empty function'),
            (r'class\s+\w+[^:]*:\s*\n\s*pass\b', 'empty_class', 'Empty class'),
            (r'if\s+[^:]+:\s*\n\s*pass\b', 'empty_if', 'Empty if block'),
            (r'for\s+[^:]+:\s*\n\s*pass\b', 'empty_loop', 'Empty loop'),
            (r'else\s*:\s*\n\s*pass\b', 'empty_else', 'Empty else block'),
            (r'try\s*:\s*\n\s*pass\b', 'empty_try', 'Empty try block'),
            (r'function\s+\w+\s*\([^)]*\)\s*\{\s*\}', 'empty_function_js', 'Empty JavaScript function'),
        ]
        
        for pattern, issue_type, title in empty_patterns:
            for match in re.finditer(pattern, content):
                line_num = content[:match.start()].count('\n') + 1
                self.issues.append({
                    'type': issue_type,
                    'severity': 'warning',
                    'title': title,
                    'description': f"Empty code block found",
                    'file': rel_path,
                    'line': line_num,
                    'code': lines[line_num - 1][:80] if line_num <= len(lines) else '',
                    'suggestion': 'Implement the logic or remove the empty block',
                    'confidence': 0.9,
                    'lines_affected': 2
                })
                self.metrics['dead_code_lines'] += 2
    
    def _detect_unreachable_patterns(self, rel_path: str, content: str, lines: List[str]):
        """Detect unreachable code patterns"""
        unreachable_patterns = [
            (r'return\s+[^\n]+\n\s*\w+', 'unreachable_after_return', 'Code after return statement'),
            (r'break\s*\n\s*\w+', 'unreachable_after_break', 'Code after break statement'),
            (r'continue\s*\n\s*\w+', 'unreachable_after_continue', 'Code after continue statement'),
            (r'raise\s+\w+\s*\n\s*\w+', 'unreachable_after_raise', 'Code after raise statement'),
            (r'throw\s+\w+\s*;?\s*\n\s*\w+', 'unreachable_after_throw', 'Code after throw statement'),
            (r'if\s+False\s*:', 'unreachable_if_false', 'If False block will never execute'),
            (r'if\s+0\s*:\s*\n', 'unreachable_if_zero', 'If 0 block will never execute'),
        ]
        
        for pattern, issue_type, title in unreachable_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line_num = content[:match.start()].count('\n') + 1
                self.issues.append({
                    'type': issue_type,
                    'severity': 'warning',
                    'title': title,
                    'description': f"Code after control flow exit will never execute",
                    'file': rel_path,
                    'line': line_num,
                    'code': lines[line_num - 1][:80] if line_num <= len(lines) else '',
                    'suggestion': 'Remove unreachable code or fix the control flow',
                    'confidence': 0.85,
                    'lines_affected': 1
                })
                self.metrics['dead_code_lines'] += 1
