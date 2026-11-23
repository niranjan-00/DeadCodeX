"""JavaScript / TypeScript analyzer (heuristic: lexer + regular expressions, NOT a full parser).

Reported findings are limited to patterns that can be established reliably from the token stream:
unused imports/requires, unused top-level functions/classes/variables, unused exports (potential),
and unreachable statements after return/throw/break/continue.
"""
from __future__ import annotations

import bisect
import re
from collections import Counter

from .common import MAX_SOURCE_BYTES, RawFinding, numbered, range_bytes, read_text, severity_for, split_lines
from .jsscan import WORD_RE, scan_js

NODE_BUILTINS = set(("assert buffer child_process cluster crypto dgram dns events fs http http2 https net os path perf_hooks process "
                     "querystring readline stream string_decoder timers tls url util v8 vm worker_threads zlib").split())
ENTRY_STEMS = {"index", "main", "app", "server", "cli", "entry", "bootstrap", "setup", "polyfills", "worker", "service-worker"}
IMPORT_RE = re.compile(r"""^[ \t]*import\s+(?P<type>type\s+)?(?P<clause>[^;'"`]*?)\s*\bfrom\s*(?P<q>['"])(?P<mod>[^'"\n]+)(?P=q)[ \t]*(?P<semi>;?)""", re.M)
REQUIRE_RE = re.compile(r"""^[ \t]*(?P<decl>const|let|var)\s+(?P<lhs>[A-Za-z_$][\w$]*|\{[^{}=]*\})\s*=\s*require\(\s*(?P<q>['"])(?P<mod>[^'"\n]+)(?P=q)\s*\)(?![\w$.(\[])[ \t]*(?P<semi>;?)""", re.M)
DECL_FN = re.compile(r"^[ \t]*(?P<exp>export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)\s*[(<]", re.M)
DECL_CLASS = re.compile(r"^[ \t]*(?P<exp>export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)", re.M)
DECL_VAR = re.compile(r"^[ \t]*(?P<exp>export\s+)?(?P<kw>const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=;\n]+)?=(?!=)", re.M)
DECL_TYPE = re.compile(r"^[ \t]*(?P<exp>export\s+)?(?:declare\s+)?(?P<kw>interface|type|enum)\s+(?P<name>[A-Za-z_$][\w$]*)", re.M)
FN_RHS = re.compile(r"^(?:async\s+)?(?:function\b|\([^)]*\)\s*(?::[^=;{]+)?=>|[A-Za-z_$][\w$]*\s*=>)")
JSX_HINT = re.compile(r"<[A-Za-z][\w.]*(?:\s[^<>]*)?/?>")


def is_test_js(rel: str) -> bool:
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    return ("__tests__" in low or "/test/" in low or "/tests/" in low or ".test." in name or ".spec." in name
            or name.endswith((".stories.js", ".stories.tsx", ".stories.ts", ".stories.jsx")) or "/cypress/" in low or "/e2e/" in low)


def is_entry_like(rel: str) -> bool:
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    return (stem in ENTRY_STEMS or ".config." in name or name.endswith(".d.ts") or any(seg in low for seg in ("/pages/", "/app/", "/routes/", "/api/", "/migrations/"))
            or low.startswith(("pages/", "app/", "routes/", "api/", "bin/", "scripts/")))


def classify_js_module(mod: str) -> str:
    if mod.startswith((".", "/", "@/", "~/", "#")):
        return "local"
    base = mod[5:] if mod.startswith("node:") else mod
    if mod.startswith("node:") or base.split("/")[0] in NODE_BUILTINS:
        return "builtin"
    return "third-party"


def parse_clause(clause: str):
    default = ns = None
    named = []
    c = clause.strip()
    m = re.search(r"\{(.*)\}", c, re.S)
    rest = c
    if m:
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            is_type = bool(re.match(r"^type\s+", part))
            part = re.sub(r"^type\s+", "", part)
            if re.search(r"\s+as\s+", part):
                imp, loc = [x.strip() for x in re.split(r"\s+as\s+", part, 1)]
            else:
                imp = loc = part
            named.append([imp, loc, is_type])
        rest = (c[: m.start()] + c[m.end():]).strip().strip(",").strip()
    for p in [x.strip() for x in rest.split(",") if x.strip()]:
        m3 = re.match(r"^\*\s*as\s+([\w$]+)$", p)
        if m3:
            ns = m3.group(1)
        elif re.match(r"^[\w$]+$", p):
            default = p
        else:
            return None
    return default, ns, named


def parse_destructure(lhs: str):
    if not lhs.startswith("{"):
        return lhs, []
    named = []
    for part in lhs.strip("{} \t\n").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            imp, loc = [x.strip() for x in part.split(":", 1)]
        else:
            imp = loc = part
        if not re.match(r"^[\w$]+$", imp) or not re.match(r"^[\w$]+$", loc):
            return None
        named.append([imp, loc])
    return None, named


def match_close(code: str, open_pos: int, open_ch="{", close_ch="}"):
    depth = 0
    for i in range(open_pos, len(code)):
        c = code[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return None


class JsFileAnalyzer:
    def __init__(self, rel, text, view, idx, ctx, lang):
        self.rel, self.text, self.view, self.idx, self.ctx, self.lang = rel, text, view, idx, ctx, lang
        self.lines = split_lines(text)
        self.starts = [0]
        for l in self.lines:
            self.starts.append(self.starts[-1] + len(l))
        self.findings = []
        self.notes = Counter()
        self.words = Counter(WORD_RE.findall(view.nocomment))
        self.jsx = rel.endswith((".jsx", ".tsx")) or bool(JSX_HINT.search(view.code))
        self.is_module = bool(re.search(r"^[ \t]*(?:import\b|export\b)|\brequire\s*\(|\bmodule\.exports\b|\bexports\.", view.code, re.M))
        # depth at start of each line (structure view)
        self.line_depth = []
        d = 0
        for ln in range(len(self.lines)):
            self.line_depth.append(d)
            for ch in view.code[self.starts[ln]:self.starts[ln + 1]]:
                if ch in "{([":
                    d += 1
                elif ch in "})]":
                    d -= 1

    def line_of(self, pos):
        return bisect.bisect_right(self.starts, pos)

    def only_ws_before(self, pos):
        ls = self.starts[self.line_of(pos) - 1]
        return not self.view.code[ls:pos].strip()

    def only_ws_after(self, pos):
        ln = self.line_of(max(pos - 1, 0))
        le = self.starts[ln]
        return not self.view.code[pos:le].strip()

    def add(self, category, start, end, certainty, conf, symbol="", title="", fix_mode="manual", plan=None, evidence=None, extra=None):
        f = RawFinding(category=category, file=self.rel, line=start, end_line=end, certainty=certainty, confidence=max(5, min(99, int(conf))),
                       language=self.lang, symbol=symbol, title=title, fix_mode=fix_mode, item_type="code",
                       size_bytes=range_bytes(self.lines, start, end), snippet=numbered(self.lines, start, end),
                       evidence=evidence or [], extra=extra or {}, plan=plan or {})
        f.severity = severity_for(category, f.size_bytes, end - start + 1, certainty)
        self.findings.append(f)

    def del_plan(self, start, end):
        if start > 1 and not self.lines[start - 2].strip():
            while end < len(self.lines) and not self.lines[end].strip():
                end += 1
        return {"op": "delete_lines", "start": start, "end": end}

    # ------------------------------------------------------------------ imports
    def check_imports(self):
        code = self.view.code
        words = self.words

        def used_elsewhere(name, span_text):
            inside = Counter(WORD_RE.findall(span_text))
            return words[name] - inside[name] > 0

        for m in IMPORT_RE.finditer(self.view.nocomment):
            kw_pos = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
            if code[kw_pos:kw_pos + 6] != "import":
                continue
            parsed = parse_clause(m.group("clause"))
            if parsed is None:
                continue
            default, ns, named = parsed
            if not (default or ns or named):
                continue
            start, end = self.line_of(kw_pos), self.line_of(m.end() - 1)
            span = self.view.nocomment[kw_pos:m.end()]
            mod = m.group("mod")
            self._import_findings("import", start, end, kw_pos, m, span, mod, default, ns, named, used_elsewhere,
                                  extra_plan={"type_only": bool(m.group("type"))})
        for m in REQUIRE_RE.finditer(self.view.nocomment):
            kw_pos = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
            if not (code[kw_pos:kw_pos + 5] == "const" or code[kw_pos:kw_pos + 3] in ("let", "var")):
                continue
            parsed = parse_destructure(m.group("lhs"))
            if parsed is None:
                continue
            default, named = parsed
            named = [[a, b, False] for a, b in named]
            start, end = self.line_of(kw_pos), self.line_of(m.end() - 1)
            span = self.view.nocomment[kw_pos:m.end()]
            self._import_findings("require", start, end, kw_pos, m, span, m.group("mod"), default, None, named, used_elsewhere,
                                  extra_plan={"decl": m.group("decl")})

    def _import_findings(self, style, start, end, kw_pos, m, span, mod, default, ns, named, used_elsewhere, extra_plan):
        names = []
        if default:
            names.append(("default", default))
        if ns:
            names.append(("ns", ns))
        for imp, loc, *_ in named:
            names.append((f"n:{loc}", loc))
        kind = classify_js_module(mod)
        for key, local in names:
            if self.jsx and local in ("React", "h", "Fragment", "Preact", "jsx", "jsxs"):
                continue
            if used_elsewhere(local, span):
                continue
            conf, mode = {"builtin": (95, "auto"), "local": (85, "auto"), "third-party": (75, "review")}[kind]
            ev = [f"`{local}` is imported on line {start} from '{mod}' but the name does not appear anywhere else in this file (comments excluded).",
                  f"The module is {'a Node.js built-in' if kind == 'builtin' else 'inside this project' if kind == 'local' else 'a third-party package'}."]
            if kind != "builtin":
                ev.append("Importing a module can have side effects (polyfills, registrations, CSS); removing the import only changes behaviour if you rely on that.")
            standalone_ok = self.only_ws_before(kw_pos) and self.only_ws_after(m.end())
            if not standalone_ok:
                mode = "manual"
                plan = {}
                ev.append("The statement shares its line with other code, so no automatic rewrite is generated.")
            else:
                plan = {"op": "js_import", "start": start, "end": end, "style": style, "module": mod, "quote": m.group("q"),
                        "semi": bool(m.group("semi")), "indent": self.lines[start - 1][: len(self.lines[start - 1]) - len(self.lines[start - 1].lstrip())],
                        "default": default, "namespace": ns, "named": named, "remove": [key], **extra_plan}
            self.add("unused_import", start, end, "confirmed", conf, symbol=local, title=f"Unused import '{local}'", fix_mode=mode, plan=plan,
                     evidence=ev, extra={"name": local, "full": local, "module": mod, "origin": kind, "statement": span.strip()})

    # ------------------------------------------------------------------ declarations
    def exported_names(self):
        code = self.view.code
        names = set()
        for m in re.finditer(r"\bexport\s*\{([^}]*)\}(?!\s*from)", code):
            for part in m.group(1).split(","):
                part = part.strip()
                if part:
                    names.add(re.split(r"\s+as\s+", part)[0].strip())
        for m in re.finditer(r"\bmodule\.exports\s*=\s*\{([^}]*)\}", code):
            for part in m.group(1).split(","):
                part = part.strip()
                if part:
                    names.add(part.split(":")[-1].strip() if ":" in part else part)
        for m in re.finditer(r"\bmodule\.exports\s*=\s*([A-Za-z_$][\w$]*)\s*;?", code):
            names.add(m.group(1))
        for m in re.finditer(r"\bexport\s+default\s+([A-Za-z_$][\w$]*)\s*;?", code):
            names.add(m.group(1))
        for m in re.finditer(r"\bexports\.([\w$]+)\s*=\s*([A-Za-z_$][\w$]*)", code):
            names.add(m.group(2))
        return names

    def decl_end(self, kind, m):
        code = self.view.code
        pos = m.end()
        if kind in ("fn", "class", "iface"):
            if kind == "fn":
                op = code.find("(", pos - 1 if code[pos - 1] == "(" else pos)
                if op == -1:
                    return None
                cp = match_close(code, op, "(", ")")
                if cp is None:
                    return None
                search_from = cp + 1
            else:
                search_from = pos
            brace = -1
            for i in range(search_from, min(len(code), search_from + 600)):
                if code[i] == "{":
                    brace = i
                    break
                if code[i] == ";" and kind == "fn":
                    return None  # overload / declaration without body
            if brace == -1:
                return None
            close = match_close(code, brace)
            return None if close is None else close + 1
        # statement: variable or type alias
        depth = 0
        i = pos
        n = len(code)
        while i < n:
            ch = code[i]
            if ch in "{([":
                depth += 1
            elif ch in "})]":
                depth -= 1
                if depth < 0:
                    return None
            elif ch == ";" and depth == 0:
                return i + 1
            elif ch == "\n" and depth == 0:
                j = i - 1
                while j >= pos and code[j] in " \t\r":
                    j -= 1
                last = code[j] if j >= pos else ""
                k = i + 1
                while k < n and code[k] in " \t\r\n":
                    k += 1
                nxt = code[k] if k < n else ""
                if last not in "=>,+-*/&|?:(" and nxt not in ".?:+-*/&|,)]}=" and not code[j - 1:j + 1] == "=>":
                    return i
            i += 1
        return n

    def check_declarations(self):
        if is_test_js(self.rel) or self.rel.endswith(".d.ts"):
            return
        code = self.view.code
        exported_list = self.exported_names()
        entry_like = is_entry_like(self.rel)
        dyn = bool(self.idx.dynamic_js)
        decls = []
        for rx, kind in ((DECL_FN, "fn"), (DECL_CLASS, "class"), (DECL_VAR, "var"), (DECL_TYPE, "type")):
            for m in rx.finditer(code):
                ln = self.line_of(m.start())
                if self.line_depth[ln - 1] != 0:
                    continue
                decls.append((m.start(), kind, m))
        decls.sort(key=lambda d: d[0])
        for pos, kind, m in decls:
            name = m.group("name")
            if m.groupdict().get("exp") and "default" in (m.group("exp") or ""):
                continue
            dkind = kind
            if kind == "type":
                dkind = "iface" if m.group("kw") in ("interface", "enum") else "stmt"
            elif kind == "var":
                dkind = "stmt"
            end_pos = self.decl_end("fn" if kind == "fn" else "class" if kind == "class" else dkind, m)
            if end_pos is None:
                continue
            start, end = self.line_of(pos), self.line_of(max(pos, end_pos - 1))
            exported = bool(m.groupdict().get("exp")) or name in exported_list
            # classes with decorators (framework registration) are skipped
            prev = start - 2
            while prev >= 0 and not self.lines[prev].strip():
                prev -= 1
            if prev >= 0 and self.lines[prev].strip().startswith("@"):
                self.notes["decorated classes/functions (framework registration) - not reported"] += 1
                continue
            sym_kind = {"fn": "function", "class": "class", "type": m.group("kw") if kind == "type" else "type", "var": "variable"}[kind]
            category = "unused_class" if kind in ("class", "type") else "unused_function" if kind == "fn" else "unused_variable"
            if kind == "var":
                rhs = self.view.nocomment[m.end():m.end() + 240].lstrip()
                if rhs.startswith("require("):
                    continue
                if FN_RHS.match(rhs):
                    category, sym_kind = "unused_function", "function"
            ext = self.idx.external_refs(self.rel, self.lang, name, start, end)
            if ext > 0:
                continue
            ev = [f"Searched {self.idx.n_code_files} source files and {self.idx.n_other_files} other text files (HTML, JSON, configs...) for the identifier `{name}`.",
                  f"{ext} reference(s) found outside its own declaration (lines {start}-{end} of {self.rel})."]
            if exported:
                if entry_like or not self.is_module or name.startswith("_"):
                    self.notes["exports in entry-point/framework-convention files - not reported"] += 1
                    continue
                if kind == "type" and dkind == "stmt":
                    pass
                ev.append(f"`{name}` is exported, but no other file in the project mentions it. Code outside this project (a published package, another repository) could still import it.")
                conf, certainty, mode, cat = 55, "potential", "review", "unused_export"
                if dyn:
                    conf -= 15
                    ev.extend(f"The project uses {f} in {r} ({c}x), so access by name cannot be ruled out." for f, r, c in self.idx.dynamic_js[:2])
                plan = self.del_plan(start, end) if self.only_ws_before(pos) and self.only_ws_after(end_pos) else {}
                if not plan:
                    mode = "manual"
                self.add(cat, start, end, certainty, conf, symbol=name, title=f"Unused export '{name}'", fix_mode=mode, plan=plan, evidence=ev,
                         extra={"name": name, "kind": sym_kind, "exported": True})
                continue
            certainty, conf, mode = "confirmed", 88, "auto"
            if not self.is_module:
                certainty, conf, mode = "potential", 60, "review"
                ev.append("This file is a plain script (no import/export), so its top-level names are globals that HTML or code outside this project could call.")
            if dyn:
                certainty, conf, mode = "potential", min(conf, 60), "review"
                ev.extend(f"The project uses {f} in {r} ({c}x), so access by name cannot be ruled out." for f, r, c in self.idx.dynamic_js[:2])
            if category == "unused_variable":
                rhs_code = code[m.end():end_pos]
                if re.search(r"[(]|\bnew\b|\bawait\b|\+\+|--|=>", rhs_code):
                    mode = "manual"
                    ev.append("The initialiser contains a call or other expression that might have side effects, so removal is left to you.")
                elif mode == "auto":
                    mode = "review"
            if mode != "manual" and not (self.only_ws_before(pos) and self.only_ws_after(end_pos)):
                mode = "manual"
                ev.append("The declaration shares lines with other code; no automatic rewrite generated.")
            plan = self.del_plan(start, end) if mode != "manual" else {}
            self.add(category, start, end, certainty, conf, symbol=name,
                     title=f"Unused {sym_kind} '{name}'" if category != "unused_variable" else f"Unused variable '{name}'",
                     fix_mode=mode, plan=plan, evidence=ev,
                     extra={"name": name, "kind": sym_kind, "exported": False, "scope": "module", "how": "delete", "level": "module",
                            "private": False, "owner": None})

    # ------------------------------------------------------------------ unreachable
    def check_unreachable(self):
        code = self.view.code
        n = len(code)
        for m in re.finditer(r"\b(return|throw|break|continue)\b", code):
            kw, pos = m.group(1), m.start()
            k = pos - 1
            while k >= 0 and code[k] in " \t\r\n":
                k -= 1
            if k >= 0 and code[k] not in ";{}":
                continue
            j, depth, end = m.end(), 0, None
            while j < n:
                ch = code[j]
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif ch == ";" and depth == 0:
                    end = j + 1
                    break
                j += 1
            if end is None:
                continue
            t = end
            while t < n and code[t] in " \t\r\n;":
                t += 1
            if t >= n or code[t] == "}" or re.match(r"(?:case|default)\b", code[t:t + 8]):
                continue
            depth, u, last = 0, t, t
            while u < n:
                ch = code[u]
                if ch in "{([":
                    depth += 1
                elif ch in "})]":
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and re.match(r"(?:case|default)\b", code[u:u + 8]) and not (code[u - 1].isalnum() or code[u - 1] in "_$"):
                    break
                if not ch.isspace():
                    last = u
                u += 1
            region = code[t:last + 1]
            if re.search(r"\bfunction\b", region):
                self.notes["code after return containing function declarations (hoisted) - not reported"] += 1
                continue
            s_line, e_line, term_line = self.line_of(t), self.line_of(last), self.line_of(end - 1)
            clean = s_line > term_line and self.only_ws_before(t) and self.only_ws_after(last + 1)
            ev = [f"The `{kw};` statement on line {self.line_of(pos)} always leaves this block, so lines {s_line}-{e_line} can never run.",
                  "Determined from the token structure (brace nesting); the statement is terminated by a semicolon so there is no automatic-semicolon-insertion ambiguity."]
            self.add("unreachable_code", s_line, e_line, "confirmed", 90, symbol=kw, title=f"Unreachable code after '{kw}'",
                     fix_mode="auto" if clean else "manual", plan={"op": "delete_lines", "start": s_line, "end": e_line} if clean else {}, evidence=ev,
                     extra={"terminator": kw, "terminator_line": self.line_of(pos), "count": e_line - s_line + 1})

    def run(self):
        self.check_imports()
        self.check_declarations()
        self.check_unreachable()
        return self.findings


def analyze_js(project, idx, settings, ctx, progress=None, languages=("javascript", "typescript")):
    findings, notes = [], Counter()
    files = [f for f in project.files if f.lang in languages and not f.name.endswith(".d.ts")]
    for n, pf in enumerate(files):
        if progress and n % 50 == 0:
            progress(int(60 + 15 * n / max(1, len(files))), f"Analyzing JavaScript/TypeScript ({n}/{len(files)} files)")
        if pf.size > MAX_SOURCE_BYTES:
            project.notes.append(f"{pf.rel}: skipped (larger than {MAX_SOURCE_BYTES // 1024 // 1024} MB)")
            continue
        text = read_text(pf.abs, MAX_SOURCE_BYTES)
        if text is None:
            continue
        view = idx.js_views.get(pf.rel) or scan_js(text, jsx=pf.ext in (".jsx", ".tsx"))
        if not view.ok:
            notes[f"{pf.rel}: brackets/strings could not be balanced by the lexer (JSX text, unusual syntax) - file not analyzed"] += 1
            continue
        a = JsFileAnalyzer(pf.rel, text, view, idx, ctx, pf.lang)
        findings.extend(a.run())
        notes.update(a.notes)
    return findings, notes
