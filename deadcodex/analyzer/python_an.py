"""Python analyzer based on the standard-library `ast` module (no code is ever executed)."""
from __future__ import annotations

import ast
from collections import Counter

from .common import RawFinding, numbered, range_bytes, read_text, severity_for, split_lines, stdlib_names, MAX_SOURCE_BYTES

STDLIB = stdlib_names()
ALLOWED_DECORATORS = {"staticmethod", "classmethod", "property", "cached_property", "lru_cache", "cache", "functools.lru_cache",
                      "functools.cache", "functools.cached_property", "abc.abstractmethod_never"}
ENTRY_FUNCS = {"lambda_handler", "handler", "application", "create_app", "make_app", "wsgi_app"}
CONFIG_FILE_STEMS = {"settings", "config", "configuration", "constants", "conf", "local_settings", "defaults"}
IMPURE_SAFE_NODES = (ast.Constant, ast.Name)


def is_test_file(rel: str) -> bool:
    parts = rel.lower().split("/")
    name = parts[-1]
    return ("tests" in parts[:-1] or "test" in parts[:-1] or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py")


def dec_name(d) -> str:
    if isinstance(d, ast.Call):
        return dec_name(d.func)
    if isinstance(d, ast.Attribute):
        return f"{dec_name(d.value)}.{d.attr}"
    if isinstance(d, ast.Name):
        return d.id
    return "?"


def decorated_start(node) -> int:
    return min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])


def is_pure(node) -> bool:
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.UnaryOp):
        return is_pure(node.operand)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(is_pure(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and is_pure(k) and is_pure(v) for k, v in zip(node.keys, node.values))
    return False


def standalone(lines, node) -> bool:
    """True if the statement occupies whole lines (no `a; b` sharing)."""
    first = lines[node.lineno - 1]
    prefix = first.encode("utf-8", "replace")[: node.col_offset].decode("utf-8", "ignore")
    if prefix.strip():
        return False
    last = lines[node.end_lineno - 1]
    suffix = last.encode("utf-8", "replace")[node.end_col_offset:].decode("utf-8", "ignore").strip()
    return suffix == "" or suffix.startswith("#")


def line_indent(lines, lineno) -> str:
    l = lines[lineno - 1]
    return l[: len(l) - len(l.lstrip())]


def extend_blank(lines, start, end):
    """Collapse the blank gap left behind: if blank lines precede `start`, also take trailing blanks."""
    if start > 1 and not lines[start - 2].strip():
        while end < len(lines) and not lines[end].strip():
            end += 1
    return start, end


def has_comment(lines, start, end) -> bool:
    return any("#" in l for l in lines[start - 1:end])


def child_bodies(node):
    for fld in ("body", "orelse", "finalbody"):
        b = getattr(node, fld, None)
        if isinstance(b, list) and b and isinstance(b[0], ast.stmt):
            yield b
    if isinstance(node, ast.Try):
        for h in node.handlers:
            if h.body:
                yield h.body
    for c in getattr(node, "cases", []) or []:
        if c.body:
            yield c.body


class PyFileAnalyzer:
    def __init__(self, rel, text, tree, idx, ctx):
        self.rel, self.text, self.tree, self.idx, self.ctx = rel, text, tree, idx, ctx
        self.lines = split_lines(text)
        self.findings = []
        self.notes = Counter()
        self.parent_body = {}
        for node in ast.walk(tree):
            for body in child_bodies(node):
                for s in body:
                    self.parent_body[id(s)] = body
        self.name_loads = set()
        self.annotation_strings = ""
        self.all_names = set()
        self.uses_locals = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
                self.name_loads.add(node.id)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("locals", "vars", "eval", "exec", "globals"):
                self.uses_locals = True
            ann = []
            if isinstance(node, ast.arg) and node.annotation is not None:
                ann.append(node.annotation)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
                ann.append(node.returns)
            if isinstance(node, ast.AnnAssign):
                ann.append(node.annotation)
            for a in ann:
                for c in ast.walk(a):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        self.annotation_strings += " " + c.value
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                        for e in node.value.elts:
                            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                                self.all_names.add(e.value)
        import re
        self._annotation_words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", self.annotation_strings))

    # ------------------------------------------------------------ helpers
    def sole(self, stmt) -> bool:
        body = self.parent_body.get(id(stmt))
        return body is not None and len(body) == 1 and body is not self.tree.body

    def del_plan(self, node, start=None, end=None, force_sole=None):
        start = start or decorated_start(node)
        end = end or node.end_lineno
        sole = self.sole(node) if force_sole is None else force_sole
        indent = line_indent(self.lines, node.lineno)
        if sole:
            return {"op": "replace_lines", "start": start, "end": end, "text": indent + "pass\n", "sole": True}
        s, e = extend_blank(self.lines, start, end)
        return {"op": "delete_lines", "start": s, "end": e}

    def add(self, category, start, end, certainty, conf, symbol="", title="", fix_mode="manual", plan=None, evidence=None, extra=None):
        f = RawFinding(category=category, file=self.rel, line=start, end_line=end, certainty=certainty, confidence=max(5, min(99, int(conf))),
                       language="python", symbol=symbol, title=title, fix_mode=fix_mode, item_type="code",
                       size_bytes=range_bytes(self.lines, start, end), snippet=numbered(self.lines, start, end),
                       evidence=evidence or [], extra=extra or {}, plan=plan or {})
        f.severity = severity_for(category, f.size_bytes, end - start + 1, certainty)
        self.findings.append(f)
        return f

    # ------------------------------------------------------------ imports
    def classify_module(self, module: str, level: int) -> str:
        if level:
            return "local"
        top = (module or "").split(".")[0]
        if top in STDLIB:
            return "stdlib"
        if top in self.idx.py_top_modules:
            return "local"
        return "third-party"

    def check_imports(self):
        if self.rel.endswith("__init__.py"):
            return
        guarded = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Try):
                for stmt in node.body + [s for h in node.handlers for s in h.body] + node.orelse + node.finalbody:
                    for c in ast.walk(stmt):
                        if isinstance(c, (ast.Import, ast.ImportFrom)):
                            guarded.add(id(c))
            if isinstance(node, ast.If):
                t = ast.dump(node.test)
                if "TYPE_CHECKING" in t:
                    for stmt in node.body:
                        for c in ast.walk(stmt):
                            if isinstance(c, (ast.Import, ast.ImportFrom)):
                                guarded.add(id(c))
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) in guarded:
                self.notes["imports inside try/except or TYPE_CHECKING were not reported"] += 1
                continue
            if isinstance(node, ast.ImportFrom) and (node.module == "__future__" or any(a.name == "*" for a in node.names)):
                continue
            seg = "".join(self.lines[node.lineno - 1:node.end_lineno])
            if "noqa" in seg.lower():
                continue
            unused = []
            for i, a in enumerate(node.names):
                bound = a.asname or a.name.split(".")[0]
                if bound in self.name_loads or bound in self.all_names or bound in self._annotation_words:
                    continue
                unused.append((i, a, bound))
            if not unused:
                continue
            module = ("." * node.level) + (node.module or "") if isinstance(node, ast.ImportFrom) else ""
            kind_mod = self.classify_module(node.module or "", node.level) if isinstance(node, ast.ImportFrom) else self.classify_module(node.names[0].name, 0)
            for i, a, bound in unused:
                mod_for_class = (node.module or "") if isinstance(node, ast.ImportFrom) else a.name
                kind = self.classify_module(mod_for_class, node.level if isinstance(node, ast.ImportFrom) else 0)
                conf, mode = {"stdlib": (95, "auto"), "local": (85, "auto"), "third-party": (75, "review")}[kind]
                certainty = "confirmed"
                evidence = [f"`{bound}` is imported on line {node.lineno} but never used anywhere else in this file (no name reference, not in __all__, not in a type annotation).",
                            f"The imported module is {'part of the Python standard library' if kind == 'stdlib' else 'inside this project' if kind == 'local' else 'a third-party package'}."]
                if self.uses_locals:
                    conf, certainty, mode = 55, "potential", "review"
                    evidence.append("This file calls locals()/globals()/eval()/exec(), so a name could be used indirectly.")
                if kind != "stdlib":
                    evidence.append("Importing a module can have side effects (registering plugins, configuring libraries); removal is only safe if you do not rely on that.")
                commented = has_comment(self.lines, node.lineno, node.end_lineno)
                plan = {"op": "py_import", "start": node.lineno, "end": node.end_lineno, "indent": line_indent(self.lines, node.lineno),
                        "kind": "import" if isinstance(node, ast.Import) else "from", "module": module,
                        "aliases": [[x.name, x.asname] for x in node.names], "remove": [i], "sole": self.sole(node)}
                if commented and mode == "auto":
                    mode = "review"
                    evidence.append("The statement has a comment on it that would be lost; please review.")
                full = f"{a.name} as {a.asname}" if a.asname else a.name
                self.add("unused_import", node.lineno, node.end_lineno, certainty, conf, symbol=bound,
                         title=f"Unused import '{bound}'", fix_mode=mode, plan=plan, evidence=evidence,
                         extra={"name": bound, "full": full, "module": module or a.name, "origin": kind, "statement": seg.strip()})

    # ------------------------------------------------------------ unused definitions
    def _dynamic_evidence(self):
        out = []
        for feat, rel, count in self.idx.dynamic_py[:3]:
            out.append(f"The project uses {feat} in {rel} ({count}x), so static analysis cannot rule out dynamic access by name.")
        return out

    def _symbol_evidence(self, name, start, end, ext_refs, str_loc):
        n_code, n_other = self.idx.n_code_files, self.idx.n_other_files
        ev = [f"Searched {n_code} source files and {n_other} other text files (templates, configs, markup) for the identifier `{name}`.",
              f"{ext_refs} reference(s) found outside its own definition (lines {start}-{end} of {self.rel})."]
        if str_loc:
            ev.append(f"The text `{name}` appears inside a string literal in {str_loc[0]}: \"{str_loc[1]}\" - this may be a dynamic/by-name reference (getattr, url_for, entry points).")
        return ev

    def scan_defs(self):
        lib_like = self.ctx["library_like"](self.rel)
        in_tests = is_test_file(self.rel)
        dyn_present = bool(self.idx.dynamic_py)

        def handle_function(fn, owner):
            name = fn.name
            start, end = decorated_start(fn), fn.end_lineno
            if name.startswith("__") and name.endswith("__"):
                return
            decs = [dec_name(d) for d in fn.decorator_list]
            bad = [d for d in decs if d not in ALLOWED_DECORATORS]
            if bad:
                for d in bad:
                    self.notes[f"decorated with @{d} (registered by a framework?) - not reported"] += 1
                return
            if in_tests and (name.startswith("test") or name in ("setUp", "tearDown", "setUpClass", "tearDownClass")):
                return
            if name in self.all_names or name in ENTRY_FUNCS:
                return
            ext = self.idx.external_refs(self.rel, "python", name, start, end)
            if ext > 0:
                return
            private = name.startswith("_")
            str_refs = self.idx.string_words[name]
            str_loc = self.idx.string_ref_location(name) if str_refs else None
            if owner is None:
                kind = "function"
                public_api = (not private) and lib_like
                conf = 90 if private else 80
                if public_api:
                    conf = 55
            else:
                has_bases = owner["has_bases"]
                kind = "method"
                if has_bases and not private:
                    self.notes["methods of classes with base classes (may override/implement framework hooks) - not reported"] += 1
                    return
                if owner["test_case"]:
                    return
                conf = 85 if private else 60
                public_api = not private
            certainty = "confirmed"
            ev = self._symbol_evidence(name, start, end, ext, str_loc)
            if public_api:
                certainty = "potential"
                ev.append("It has a public name inside an installable package, so code outside this project may import it.")
            elif owner is not None and not private:
                certainty = "potential"
                ev.append("Public methods can be called from outside this project or through duck typing.")
            if str_loc:
                conf -= 25
                certainty = "potential"
            if dyn_present:
                conf -= 15
                certainty = "potential"
                ev.extend(self._dynamic_evidence())
            ev.append("Private name (leading underscore) - conventionally not part of any public API." if private else "Public name.")
            conf = max(10, conf)
            safe_auto = (certainty == "confirmed" and private and not dyn_present and not str_loc and standalone(self.lines, fn))
            sole = self.sole(fn)
            if sole:
                mode, plan = "manual", {}
                ev.append("It is the only statement in its block; deleting it would leave an empty block. Replace it with `pass` or remove the whole block manually.")
            else:
                plan = self.del_plan(fn) if standalone(self.lines, fn) else {}
                mode = "auto" if (safe_auto and plan) else ("review" if plan else "manual")
            self.add("unused_function", start, end, certainty, conf, symbol=name,
                     title=f"Unused {kind} '{name}'", fix_mode=mode, plan=plan, evidence=ev,
                     extra={"name": name, "kind": kind, "private": private, "owner": owner["name"] if owner else None,
                            "params": [a.arg for a in fn.args.args]})

        def handle_class(c):
            name = c.name
            start, end = decorated_start(c), c.end_lineno
            if c.decorator_list:
                for d in c.decorator_list:
                    self.notes[f"class decorated with @{dec_name(d)} - not reported"] += 1
                return
            if name in self.all_names:
                return
            if in_tests and name.startswith("Test"):
                return
            base_names = []
            for b in c.bases:
                try:
                    base_names.append(ast.unparse(b))
                except Exception:
                    base_names.append("?")
            real_bases = [b for b in base_names if b != "object"]
            has_bases = bool(real_bases or c.keywords)
            ext = self.idx.external_refs(self.rel, "python", name, start, end)
            if ext > 0:
                return
            str_refs = self.idx.string_words[name]
            str_loc = self.idx.string_ref_location(name) if str_refs else None
            private = name.startswith("_")
            conf = 90 if private else 80
            certainty = "confirmed"
            ev = self._symbol_evidence(name, start, end, ext, str_loc)
            if has_bases:
                conf = min(conf, 50)
                certainty = "potential"
                ev.append(f"It inherits from {', '.join(real_bases) or 'a base class with options'}; subclasses of framework classes (ORM models, forms, plugins) are often discovered by the framework instead of being referenced by name.")
            elif lib_like and not private:
                conf, certainty = 55, "potential"
                ev.append("It has a public name inside an installable package, so code outside this project may import it.")
            if str_loc:
                conf -= 25
                certainty = "potential"
            if dyn_present:
                conf -= 15
                certainty = "potential"
                ev.extend(self._dynamic_evidence())
            conf = max(10, conf)
            sole = self.sole(c)
            plan = {} if sole else (self.del_plan(c) if standalone(self.lines, c) else {})
            mode = "review" if plan else "manual"
            if sole:
                ev.append("It is the only statement in its block; deleting it would leave an empty block.")
            self.add("unused_class", start, end, certainty, conf, symbol=name, title=f"Unused class '{name}'", fix_mode=mode, plan=plan,
                     evidence=ev, extra={"name": name, "kind": "class", "bases": real_bases, "methods": [m.name for m in c.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]})

        def walk_body(body, owner=None):
            for st in body:
                if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    handle_function(st, owner)
                    walk_body(st.body, None)  # nested functions
                elif isinstance(st, ast.ClassDef):
                    if owner is None:
                        handle_class(st)
                    bases = [ast.unparse(b) for b in st.bases] if hasattr(ast, "unparse") else []
                    info = {"name": st.name, "has_bases": any(b != "object" for b in bases) or bool(st.keywords),
                            "test_case": any("TestCase" in b for b in bases)}
                    walk_body([s for s in st.body], info)
                else:
                    for b in child_bodies(st):
                        walk_body(b, owner)

        walk_body(self.tree.body)

    # ------------------------------------------------------------ variables
    def check_local_variables(self):
        for fn in ast.walk(self.tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            sub = list(ast.walk(fn))
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("locals", "vars", "eval", "exec") for n in sub):
                continue
            declared = set()
            for n in sub:
                if isinstance(n, (ast.Global, ast.Nonlocal)):
                    declared.update(n.names)
            loads = {n.id for n in sub if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Load, ast.Del))}
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs + getattr(fn.args, "posonlyargs", [])}
            if fn.args.vararg:
                params.add(fn.args.vararg.arg)
            if fn.args.kwarg:
                params.add(fn.args.kwarg.arg)

            def own_statements(body):
                for st in body:
                    yield st
                    if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                        continue
                    for b in child_bodies(st):
                        yield from own_statements(b)

            for st in own_statements(fn.body):
                target = value = None
                if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                    target, value = st.targets[0].id, st.value
                elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
                    target, value = st.target.id, st.value
                if not target or target.startswith("_") or target in loads or target in declared or target in params:
                    continue
                if not standalone(self.lines, st) or has_comment(self.lines, st.lineno, st.end_lineno):
                    plan, mode, how = {}, "manual", "none"
                elif is_pure(value):
                    plan, mode, how = self.del_plan(st), "auto", "delete"
                else:
                    seg = ast.get_source_segment(self.text, value) or ""
                    indent = line_indent(self.lines, st.lineno)
                    plan = {"op": "replace_lines", "start": st.lineno, "end": st.end_lineno, "text": indent + seg + "\n"}
                    mode, how = "auto", "keep_call"
                ev = [f"`{target}` is assigned in function `{fn.name}` (line {st.lineno}) but never read anywhere in that function (including nested functions).",
                      "The function does not use locals(), vars(), eval(), exec() or global/nonlocal for this name."]
                if how == "keep_call":
                    ev.append("The right-hand side is a call/expression that may have side effects, so the fix keeps the expression and only drops the unused name.")
                self.add("unused_variable", st.lineno, st.end_lineno, "confirmed", 92, symbol=target,
                         title=f"Unused local variable '{target}'", fix_mode=mode, plan=plan, evidence=ev,
                         extra={"name": target, "scope": fn.name, "how": how, "level": "local"})

    def check_module_variables(self):
        stem = self.rel.rsplit("/", 1)[-1][:-3]
        if stem in CONFIG_FILE_STEMS or self.rel.endswith("__init__.py") or is_test_file(self.rel):
            return
        for st in self.tree.body:
            if not (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)):
                continue
            name = st.targets[0].id
            if name.startswith("__") or name == "_" or name in self.all_names:
                continue
            ext = self.idx.external_refs(self.rel, "python", name, st.lineno, st.end_lineno)
            if ext > 0 or self.idx.string_words[name] > 0:
                continue
            plan, mode = {}, "manual"
            if standalone(self.lines, st) and not has_comment(self.lines, st.lineno, st.end_lineno) and is_pure(st.value):
                plan, mode = self.del_plan(st), "review"
            dyn = bool(self.idx.dynamic_py)
            ev = [f"Module-level variable `{name}` (line {st.lineno}) has {ext} references anywhere in {self.idx.n_code_files} source and {self.idx.n_other_files} other text files.",
                  "Module-level names can be read from other modules, plugins or configuration systems, so this is a potential (not confirmed) finding."]
            if dyn:
                ev.extend(self._dynamic_evidence())
            self.add("unused_variable", st.lineno, st.end_lineno, "potential", 55 if not dyn else 40, symbol=name,
                     title=f"Unused module variable '{name}'", fix_mode=mode, plan=plan, evidence=ev,
                     extra={"name": name, "scope": "module", "how": "delete" if plan else "none", "level": "module"})

    # ------------------------------------------------------------ control flow
    def check_unreachable(self):
        def check_block(body):
            for i, st in enumerate(body):
                if isinstance(st, (ast.Return, ast.Raise, ast.Continue, ast.Break)) and i + 1 < len(body):
                    rest = body[i + 1:]
                    start = min(decorated_start(r) for r in rest[:1])
                    end = rest[-1].end_lineno
                    kw = type(st).__name__.lower()
                    clean = st.end_lineno < start and standalone(self.lines, st)
                    plan = {"op": "delete_lines", "start": start, "end": end} if clean else {}
                    ev = [f"The `{kw}` statement on line {st.lineno} always leaves this block, so lines {start}-{end} can never run.",
                          "This is determined from the program structure alone (no guesses about runtime values)."]
                    self.add("unreachable_code", start, end, "confirmed", 98, symbol=kw,
                             title=f"Unreachable code after '{kw}'", fix_mode="auto" if clean else "manual", plan=plan, evidence=ev,
                             extra={"terminator": kw, "terminator_line": st.lineno, "count": len(rest)})
                    break
        for node in ast.walk(self.tree):
            for body in child_bodies(node):
                check_block(body)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and not isinstance(node.test.value, str):
                val = bool(node.test.value)
                if not val and not node.orelse and standalone(self.lines, node):
                    ev = [f"The condition on line {node.lineno} is the constant `{ast.unparse(node.test)}`, which is always false, so the body (lines {node.body[0].lineno}-{node.end_lineno}) never runs."]
                    self.add("dead_branch", node.lineno, node.end_lineno, "confirmed", 92, symbol=ast.unparse(node.test),
                             title="Dead branch: `if %s:`" % ast.unparse(node.test), fix_mode="review", plan=self.del_plan(node), evidence=ev,
                             extra={"condition": ast.unparse(node.test), "always": False})
                elif val and node.orelse and not isinstance(node.orelse[0], ast.If):
                    else_line = None
                    for ln in range(node.orelse[0].lineno - 1, node.body[-1].end_lineno, -1):
                        if self.lines[ln - 1].strip().startswith("else") and self.lines[ln - 1].strip().rstrip().endswith(":"):
                            else_line = ln
                            break
                    end = node.orelse[-1].end_lineno
                    if else_line:
                        ev = [f"The condition on line {node.lineno} is the constant `{ast.unparse(node.test)}`, which is always true, so the `else` block (lines {else_line}-{end}) never runs."]
                        self.add("dead_branch", else_line, end, "confirmed", 92, symbol=ast.unparse(node.test),
                                 title="Dead `else` branch: `if %s:`" % ast.unparse(node.test), fix_mode="review",
                                 plan={"op": "delete_lines", "start": else_line, "end": end}, evidence=ev,
                                 extra={"condition": ast.unparse(node.test), "always": True})

    def run(self):
        self.check_imports()
        self.scan_defs()
        self.check_local_variables()
        self.check_module_variables()
        self.check_unreachable()
        return self.findings


def analyze_python(project, idx, settings, ctx, progress=None):
    findings, notes = [], Counter()
    files = [f for f in project.files if f.lang == "python"]
    for n, pf in enumerate(files):
        if progress and n % 50 == 0:
            progress(int(40 + 20 * n / max(1, len(files))), f"Analyzing Python ({n}/{len(files)} files)")
        if pf.size > MAX_SOURCE_BYTES:
            project.notes.append(f"{pf.rel}: skipped (larger than {MAX_SOURCE_BYTES // 1024 // 1024} MB)")
            continue
        text = read_text(pf.abs, MAX_SOURCE_BYTES)
        if text is None:
            continue
        import ast as _ast
        try:
            tree = _ast.parse(text, filename=pf.rel)
        except (SyntaxError, ValueError, RecursionError):
            continue
        a = PyFileAnalyzer(pf.rel, text, tree, idx, ctx)
        findings.extend(a.run())
        notes.update(a.notes)
    return findings, notes
