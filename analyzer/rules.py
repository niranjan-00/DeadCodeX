"""
DeadCodeX Regex Rule Engine
Language-specific regex patterns for code quality and dead code detection
"""
import re
from typing import List, Dict


class RegexRuleEngine:
    """
    Rule engine that applies regex-based patterns across multiple languages
    to detect code smells, dead code, and quality issues.
    """
    
    RULES = {
        'python': [
            {
                'pattern': r'^\s*import\s+(\w+)\s*(?:as\s+\w+)?\s*$',
                'type': 'unused_import',
                'severity': 'warning',
                'title': 'Potentially unused import',
                'description': 'Module imported at module level',
                'confidence': 0.6,
                'multiline': False
            },
            {
                'pattern': r'^\s*from\s+([\w.]+)\s+import\s+(.+)\s*$',
                'type': 'unused_import',
                'severity': 'warning',
                'title': 'Potentially unused import',
                'description': 'Names imported from module',
                'confidence': 0.6,
                'multiline': False
            },
            {
                'pattern': r'^\s*(?:\w+\s+)*=\s*(?:None|0|""|\'\'|\[\]|\{\})\s*$',
                'type': 'uninitialized_variable',
                'severity': 'info',
                'title': 'Variable initialized to empty/default value',
                'description': 'Variable set to empty value but may remain unused',
                'confidence': 0.4,
                'multiline': False
            },
        ],
        'javascript': [
            {
                'pattern': r'^\s*import\s+.*?\s+from\s+[\'"].*?[\'"]\s*;?\s*$',
                'type': 'unused_import',
                'severity': 'warning',
                'title': 'ES6 import statement',
                'description': 'Module import - verify it is used',
                'confidence': 0.5,
                'multiline': False
            },
            {
                'pattern': r'^\s*const\s+(\w+)\s*=\s*require\s*\(\s*[\'"].*?[\'"]\s*\)\s*;?\s*$',
                'type': 'unused_require',
                'severity': 'warning',
                'title': 'Potentially unused require',
                'description': 'Module required but may not be used',
                'confidence': 0.6,
                'multiline': False
            },
            {
                'pattern': r'^\s*var\s+\w+\s*=\s*.*?;?\s*$',
                'type': 'old_var_declaration',
                'severity': 'info',
                'title': 'Using var instead of let/const',
                'description': 'Consider using let or const for better scoping',
                'confidence': 0.7,
                'multiline': False
            },
            {
                'pattern': r'console\.(log|warn|error|debug|info)\s*\(',
                'type': 'debug_statement',
                'severity': 'info',
                'title': 'Debug console statement',
                'description': 'Console statement should be removed in production',
                'confidence': 0.8,
                'multiline': False
            },
            {
                'pattern': r'debugger\s*;?',
                'type': 'debugger_statement',
                'severity': 'warning',
                'title': 'Debugger statement',
                'description': 'Debugger statement found - remove before production',
                'confidence': 0.95,
                'multiline': False
            },
        ],
        'css': [
            {
                'pattern': r'^\s*\.([\w-]+)\s*\{[^}]*\}\s*$',
                'type': 'css_class_defined',
                'severity': 'info',
                'title': 'CSS class defined',
                'description': 'CSS class - ensure it is used in HTML/JSX',
                'confidence': 0.3,
                'multiline': True
            },
            {
                'pattern': r'color:\s*#000\s*;?',
                'type': 'redundant_css',
                'severity': 'info',
                'title': 'Redundant CSS color',
                'description': 'Black color may be default - verify necessity',
                'confidence': 0.3,
                'multiline': False
            },
        ],
        'java': [
            {
                'pattern': r'^\s*import\s+([\w.]+)\s*;\s*$',
                'type': 'unused_import',
                'severity': 'warning',
                'title': 'Java import',
                'description': 'Import statement - verify usage',
                'confidence': 0.5,
                'multiline': False
            },
            {
                'pattern': r'System\.out\.println\s*\(',
                'type': 'debug_statement',
                'severity': 'info',
                'title': 'Debug print statement',
                'description': 'System.out.println should be replaced with logging',
                'confidence': 0.8,
                'multiline': False
            },
        ],
        'cpp': [
            {
                'pattern': r'^\s*#include\s+[<"](.+?)[>"]\s*$',
                'type': 'unused_include',
                'severity': 'warning',
                'title': 'C++ include directive',
                'description': 'Include directive - verify usage',
                'confidence': 0.5,
                'multiline': False
            },
            {
                'pattern': r'std::cout\s*<<',
                'type': 'debug_statement',
                'severity': 'info',
                'title': 'Debug output statement',
                'description': 'cout debug statement',
                'confidence': 0.8,
                'multiline': False
            },
        ],
        'php': [
            {
                'pattern': r'^\s*include\s*\(?\s*[\'"].*?[\'"]\s*\)?\s*;?\s*$',
                'type': 'include_statement',
                'severity': 'info',
                'title': 'PHP include statement',
                'description': 'File include - verify path security',
                'confidence': 0.5,
                'multiline': False
            },
            {
                'pattern': r'echo\s+',
                'type': 'debug_statement',
                'severity': 'info',
                'title': 'Echo debug statement',
                'description': 'Echo statement - may be debug code',
                'confidence': 0.6,
                'multiline': False
            },
        ],
        'ruby': [
            {
                'pattern': r'^\s*require\s+[\'"].*?[\'"]\s*$',
                'type': 'unused_require',
                'severity': 'warning',
                'title': 'Ruby require statement',
                'description': 'Require statement - verify usage',
                'confidence': 0.5,
                'multiline': False
            },
            {
                'pattern': r'puts\s+',
                'type': 'debug_statement',
                'severity': 'info',
                'title': 'Debug puts statement',
                'description': 'puts debug output',
                'confidence': 0.8,
                'multiline': False
            },
        ],
        'go': [
            {
                'pattern': r'^\s*import\s+\(\s*(?:[\'"].*?[\'"]\s*)+\)\s*$',
                'type': 'unused_import',
                'severity': 'warning',
                'title': 'Go import block',
                'description': 'Import block - verify all imports used',
                'confidence': 0.5,
                'multiline': True
            },
            {
                'pattern': r'fmt\.Print(?:ln|f)?\s*\(',
                'type': 'debug_statement',
                'severity': 'info',
                'title': 'Debug print statement',
                'description': 'fmt.Print debug statement',
                'confidence': 0.8,
                'multiline': False
            },
        ],
        'general': [
            {
                'pattern': r'^\s*(?:#|//)\s*(?:TODO|FIXME|HACK|XXX|BUG)\s*:?\s*(.+)$',
                'type': 'todo_item',
                'severity': 'info',
                'title': 'Code TODO/FIXME',
                'description': 'Pending task marker found',
                'confidence': 0.95,
                'multiline': False
            },
            {
                'pattern': r'^\s*(?:#|//)\s*(?:REMOVE|DELETE|DEPRECATED|OBSOLETE)\b',
                'type': 'deprecated_marker',
                'severity': 'warning',
                'title': 'Deprecated code marker',
                'description': 'Code marked for removal or deprecation',
                'confidence': 0.8,
                'multiline': False
            },
        ]
    }
    
    def check_file(self, filepath: str, content: str, language: str) -> List[Dict]:
        """Apply all matching rules to a file"""
        issues = []
        lines = content.split('\n')
        
        # Determine which rule sets to apply
        rule_sets = ['general']
        if language in self.RULES:
            rule_sets.insert(0, language)
        else:
            # Try to match by file extension
            ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''
            ext_to_lang = {
                'py': 'python', 'js': 'javascript', 'jsx': 'javascript',
                'ts': 'javascript', 'tsx': 'javascript', 'java': 'java',
                'cpp': 'cpp', 'c': 'cpp', 'h': 'cpp', 'hpp': 'cpp',
                'cs': 'general', 'php': 'php', 'rb': 'ruby',
                'go': 'go', 'css': 'css', 'scss': 'css', 'sass': 'css'
            }
            if ext in ext_to_lang and ext_to_lang[ext] in self.RULES:
                rule_sets.insert(0, ext_to_lang[ext])
        
        # Apply rules
        for rule_set_name in rule_sets:
            for rule in self.RULES.get(rule_set_name, []):
                if rule.get('multiline', False):
                    # Multiline patterns
                    for match in re.finditer(rule['pattern'], content, re.MULTILINE):
                        line_num = content[:match.start()].count('\n') + 1
                        
                        # Skip if in comment
                        line = lines[line_num - 1] if line_num <= len(lines) else ''
                        if self._is_pure_comment(line, rule_set_name):
                            continue
                        
                        issues.append({
                            'type': rule['type'],
                            'severity': rule['severity'],
                            'title': rule['title'],
                            'description': rule['description'],
                            'file': filepath,
                            'line': line_num,
                            'code': self._get_context(lines, line_num),
                            'suggestion': self._get_suggestion(rule['type']),
                            'confidence': rule['confidence'],
                            'lines_affected': 1
                        })
                else:
                    # Line-by-line patterns
                    for idx, line in enumerate(lines):
                        if re.search(rule['pattern'], line):
                            # Skip if it's a comment explaining the pattern
                            if self._is_pure_comment(line, rule_set_name):
                                continue
                            
                            issues.append({
                                'type': rule['type'],
                                'severity': rule['severity'],
                                'title': rule['title'],
                                'description': rule['description'],
                                'file': filepath,
                                'line': idx + 1,
                                'code': line[:100],
                                'suggestion': self._get_suggestion(rule['type']),
                                'confidence': rule['confidence'],
                                'lines_affected': 1
                            })
        
        return issues
    
    def _is_pure_comment(self, line: str, language: str) -> bool:
        """Check if a line is purely a comment"""
        stripped = line.strip()
        comment_prefixes = ['#', '//', '/*', '*', '--', '%', ';']
        return any(stripped.startswith(p) for p in comment_prefixes)
    
    def _get_context(self, lines: List[str], line_num: int, context: int = 1) -> str:
        """Get code context around a line"""
        start = max(0, line_num - context - 1)
        end = min(len(lines), line_num + context)
        return '\n'.join(lines[start:end])[:150]
    
    def _get_suggestion(self, issue_type: str) -> str:
        """Get fix suggestion based on issue type"""
        suggestions = {
            'unused_import': 'Remove the unused import statement',
            'unused_require': 'Remove unused require/import',
            'unused_variable': 'Remove the variable or use it',
            'debug_statement': 'Remove debug statements before production',
            'debugger_statement': 'Remove debugger statements',
            'old_var_declaration': 'Use const or let instead of var',
            'todo_item': 'Address or remove the TODO item',
            'deprecated_marker': 'Review and remove deprecated code',
            'css_class_defined': 'Ensure CSS class is used in templates',
            'redundant_css': 'Simplify or remove redundant CSS',
            'uninitialized_variable': 'Initialize variable with meaningful value or remove',
            'unused_include': 'Remove unused include directive',
            'unused_argument': 'Remove unused function parameter',
            'include_statement': 'Verify include path is secure',
        }
        return suggestions.get(issue_type, 'Review and fix this issue')
