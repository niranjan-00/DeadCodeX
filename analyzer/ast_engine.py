"""
DeadCodeX AST Engine
Python-specific AST analysis for precise dead code detection
"""
import ast
import re
from typing import List, Dict, Set, Tuple


class PythonASTAnalyzer:
    """
    Python Abstract Syntax Tree analyzer for detecting:
    - Unused imports
    - Unused variables
    - Unused functions
    - Unused classes
    """
    
    def __init__(self, source_code: str, filepath: str = "<unknown>"):
        self.source_code = source_code
        self.filepath = filepath
        self.lines = source_code.split('\n')
        self.issues: List[Dict] = []
        
        try:
            self.tree = ast.parse(source_code)
        except SyntaxError as e:
            self.tree = None
            self.syntax_error = e
    
    def analyze(self) -> List[Dict]:
        """Run all AST-based analyses"""
        if self.tree is None:
            return [{
                'type': 'syntax_error',
                'severity': 'info',
                'title': 'Syntax Error',
                'description': f"Cannot parse file: {self.syntax_error}",
                'file': self.filepath,
                'line': getattr(self.syntax_error, 'lineno', 1),
                'code': '',
                'confidence': 1.0,
                'lines_affected': 1
            }]
        
        self._find_unused_imports()
        self._find_unused_variables()
        self._find_unused_functions()
        self._find_unused_classes()
        self._find_unused_arguments()
        self._find_redundant_pass()
        
        return self.issues
    
    def _find_unused_imports(self):
        """Detect imported modules/names that are never used"""
        imports = {}  # name -> (node, line_num, alias)
        used_names: Set[str] = set()
        
        for node in ast.walk(self.tree):
            # Collect imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name.split('.')[0]
                    imports[name] = (node, node.lineno, alias.name)
            
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports[name] = (node, node.lineno, alias.name)
            
            # Collect used names (Name nodes that are loaded, not stored)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    used_names.add(node.id)
            
            # Handle attribute access (e.g., os.path)
            elif isinstance(node, ast.Attribute):
                # Try to find the base name
                base = self._get_attribute_base(node)
                if base:
                    used_names.add(base)
        
        # Check for unused imports
        for name, (node, line_num, orig_name) in imports.items():
            if name not in used_names and name != '*':
                self.issues.append({
                    'type': 'unused_import',
                    'severity': 'warning',
                    'title': f"Unused import: '{name}'",
                    'description': f"'{orig_name}' is imported but never used in this module.",
                    'file': self.filepath,
                    'line': line_num,
                    'code': self._get_line(line_num),
                    'suggestion': f"Remove 'import {orig_name}' or use the imported module.",
                    'confidence': 0.95,
                    'lines_affected': 1
                })
    
    def _find_unused_variables(self):
        """Detect variables assigned but never read"""
        # Track assignments and uses per scope
        scope_stack = [{}]  # List of dicts: name -> [line_nums]
        use_stack = [set()]
        
        class VariableVisitor(ast.NodeVisitor):
            def __init__(self, analyzer):
                self.analyzer = analyzer
            
            def visit_FunctionDef(self, node):
                scope_stack.append({})
                use_stack.append(set())
                self.generic_visit(node)
                
                # Check unused in this scope
                current_scope = scope_stack[-1]
                current_uses = use_stack[-1]
                
                for name, lines in current_scope.items():
                    if name not in current_uses and not name.startswith('_'):
                        for line_num in lines:
                            self.analyzer.issues.append({
                                'type': 'unused_variable',
                                'severity': 'warning',
                                'title': f"Unused variable: '{name}'",
                                'description': f"Variable '{name}' is assigned but never read.",
                                'file': self.analyzer.filepath,
                                'line': line_num,
                                'code': self.analyzer._get_line(line_num),
                                'suggestion': f"Remove assignment to '{name}' or use the variable.",
                                'confidence': 0.85,
                                'lines_affected': 1
                            })
                
                scope_stack.pop()
                use_stack.pop()
            
            def visit_ClassDef(self, node):
                scope_stack.append({})
                use_stack.append(set())
                self.generic_visit(node)
                scope_stack.pop()
                use_stack.pop()
            
            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Store):
                    name = node.id
                    current = scope_stack[-1]
                    if name not in current:
                        current[name] = []
                    current[name].append(node.lineno)
                elif isinstance(node.ctx, ast.Load):
                    for uses in use_stack:
                        uses.add(node.id)
            
            def visit_arg(self, node):
                # Function arguments are implicitly assigned
                current = scope_stack[-1]
                if node.arg not in current:
                    current[node.arg] = []
                current[node.arg].append(getattr(node, 'lineno', 0))
        
        visitor = VariableVisitor(self)
        visitor.visit(self.tree)
    
    def _find_unused_functions(self):
        """Detect function definitions that might be unused (module-level only)"""
        functions = {}  # name -> (node, line_num)
        used_names = set()
        
        # Only check module-level functions
        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = (node, node.lineno)
        
        # Check for usage
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_names.add(node.id)
            # Check direct calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    used_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    base = self._get_attribute_base(node.func)
                    if base:
                        used_names.add(base)
        
        for name, (node, line_num) in functions.items():
            if name not in used_names and not name.startswith('_'):
                # Check if it might be used via string reference or decorator
                if not self._is_special_method(name):
                    self.issues.append({
                        'type': 'unused_function',
                        'severity': 'warning',
                        'title': f"Unused function: '{name}()'",
                        'description': f"Function '{name}' is defined but never called.",
                        'file': self.filepath,
                        'line': line_num,
                        'code': self._get_line(line_num),
                        'suggestion': f"Remove function '{name}' or add a call to it.",
                        'confidence': 0.75,
                        'lines_affected': node.end_lineno - node.lineno + 1 if hasattr(node, 'end_lineno') else 3
                    })
    
    def _find_unused_classes(self):
        """Detect class definitions that might be unused"""
        classes = {}  # name -> (node, line_num)
        used_names = set()
        
        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.ClassDef):
                classes[node.name] = (node, node.lineno)
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_names.add(node.id)
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    used_names.add(node.func.id)
        
        for name, (node, line_num) in classes.items():
            if name not in used_names:
                self.issues.append({
                    'type': 'unused_class',
                    'severity': 'warning',
                    'title': f"Unused class: '{name}'",
                    'description': f"Class '{name}' is defined but never instantiated.",
                    'file': self.filepath,
                    'line': line_num,
                    'code': self._get_line(line_num),
                    'suggestion': f"Remove class '{name}' or instantiate it.",
                    'confidence': 0.7,
                    'lines_affected': node.end_lineno - node.lineno + 1 if hasattr(node, 'end_lineno') else 5
                })
    
    def _find_unused_arguments(self):
        """Detect function arguments that are never used"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                if not node.args.args:
                    continue
                
                # Get argument names
                arg_names = {arg.arg for arg in node.args.args}
                if node.args.vararg:
                    arg_names.add(node.args.vararg.arg)
                if node.args.kwarg:
                    arg_names.add(node.args.kwarg.arg)
                
                # Collect used names in function body
                used_in_body = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        used_in_body.add(child.id)
                
                # Check for unused args (skip self/cls)
                for arg in node.args.args:
                    arg_name = arg.arg
                    if arg_name in ('self', 'cls', '_', 'args', 'kwargs'):
                        continue
                    if arg_name not in used_in_body:
                        self.issues.append({
                            'type': 'unused_argument',
                            'severity': 'info',
                            'title': f"Unused argument: '{arg_name}'",
                            'description': f"Argument '{arg_name}' in '{node.name}()' is not used.",
                            'file': self.filepath,
                            'line': arg.lineno if hasattr(arg, 'lineno') else node.lineno,
                            'code': self._get_line(node.lineno),
                            'suggestion': f"Remove '{arg_name}' or use it in the function body.",
                            'confidence': 0.9,
                            'lines_affected': 1
                        })
    
    def _find_redundant_pass(self):
        """Detect unnecessary pass statements"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Pass):
                # Check if parent has other statements
                parent = self._get_parent(node)
                if parent and hasattr(parent, 'body'):
                    if len(parent.body) > 1:
                        # pass is redundant if there are other statements
                        self.issues.append({
                            'type': 'redundant_pass',
                            'severity': 'info',
                            'title': "Redundant 'pass' statement",
                            'description': "This 'pass' statement is unnecessary as the block has other content.",
                            'file': self.filepath,
                            'line': node.lineno,
                            'code': self._get_line(node.lineno),
                            'suggestion': "Remove the 'pass' statement.",
                            'confidence': 0.9,
                            'lines_affected': 1
                        })
    
    def _get_attribute_base(self, node) -> str:
        """Get the base name from an attribute chain (e.g., os.path -> os)"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self._get_attribute_base(node.value)
        return None
    
    def _is_special_method(self, name: str) -> bool:
        """Check if function name is a special/dunder method"""
        return name.startswith('__') and name.endswith('__')
    
    def _get_parent(self, node):
        """Get parent node (simplified - requires tree walking)"""
        for parent in ast.walk(self.tree):
            for child in ast.iter_child_nodes(parent):
                if child is node:
                    return parent
        return None
    
    def _get_line(self, line_num: int) -> str:
        """Get a specific line from source"""
        if 1 <= line_num <= len(self.lines):
            return self.lines[line_num - 1][:100]
        return ''
