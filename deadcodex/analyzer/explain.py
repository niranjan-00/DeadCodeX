"""Plain-language explanations built from the *actual* finding data (never invented)."""
from __future__ import annotations

from ..fixes import preview_window
from .common import CATEGORY_LABELS, numbered, split_lines

WHY = {
    "unused_function": "A function/method is only useful if something calls it. The search found no call, import or other reference to this name outside its own body, so it adds code to read and maintain without doing anything.",
    "unused_class": "A class is only useful if something creates it, subclasses it or refers to it. No reference to this name was found outside the class itself.",
    "unused_import": "An import loads a module and binds a name. Here the name is never used in the file, so the import only adds start-up work and clutter.",
    "unused_variable": "A variable that is assigned but never read has no effect on the program's output; it usually is a leftover from earlier code.",
    "unused_export": "This name is exported (made available to other files) but no other file in the project mentions it.",
    "unreachable_code": "These statements come after a statement that always leaves the block (return/raise/throw/break/continue), so the computer can never reach them.",
    "dead_branch": "The condition is a constant (always true or always false), so one of the branches can never run.",
    "duplicate_code": "The same lines of code appear in more than one place. Copies must be fixed in every location when a bug is found, and they tend to drift apart.",
    "duplicate_file": "This file has exactly the same bytes as another file in the project, so one copy is redundant.",
    "junk_file": "This is a generated, temporary, cache or backup item. It is not part of the source code and normally is recreated by tools when needed.",
    "vendor_dir": "Installed third-party packages (node_modules, virtual environments) are downloaded from a package registry and normally should not be shipped with project source.",
    "unused_asset": "No file in the project refers to this image/font/media file by name, so it may be left over from a removed feature.",
    "unused_module": "No other file imports or mentions this module, and it is not a runnable script, so nothing seems to use it.",
}
CONSEQUENCE = {
    "unused_function": "Leaving it makes the codebase larger, hides the code that matters, and can mislead readers into thinking it is used. It must still be kept compiling and tested.",
    "unused_class": "It increases the amount of code to review and may be mistaken for a supported feature.",
    "unused_import": "Slightly slower start-up, longer import lists, and possible circular-import problems later.",
    "unused_variable": "Wastes a little memory/time and confuses readers about what the code computes.",
    "unused_export": "It keeps dead code alive in bundles and gives a false impression of a supported API.",
    "unreachable_code": "Readers may assume it runs; edits made there have no effect and bugs can hide in it.",
    "dead_branch": "The never-run branch still has to be maintained and can hide outdated logic.",
    "duplicate_code": "Bug fixes must be repeated in every copy; copies silently diverge.",
    "duplicate_file": "Wastes disk space and download size, and it is easy to edit the wrong copy.",
    "junk_file": "Makes the project bigger, can leak local information (logs, caches) and clutters version control.",
    "vendor_dir": "Hugely inflates archive size and can contain platform-specific binaries that do not work on other machines.",
    "unused_asset": "Increases download/bundle size for no benefit.",
    "unused_module": "Dead modules rot: they stop working as the rest of the code changes but still need to be maintained.",
}
RECOMMEND = {
    "unused_function": "Check whether it is called dynamically or from outside this project. If not, delete it.",
    "unused_class": "Check whether a framework discovers it automatically or other code imports it. If not, delete it.",
    "unused_import": "Remove the unused name from the import statement (or the whole statement).",
    "unused_variable": "Delete the assignment (if the right-hand side is a call, keep the call and drop only the name).",
    "unused_export": "If nothing outside the project imports it, remove the `export` or delete the declaration.",
    "unreachable_code": "Delete the unreachable statements.",
    "dead_branch": "Delete the branch that can never run (and simplify the condition).",
    "duplicate_code": "Move the shared lines into one function/module and call it from every place. This needs a human to design the shared function, so DeadCodeX does not rewrite it.",
    "duplicate_file": "Keep one copy and update any references to point to it, then delete the others.",
    "junk_file": "Delete it; add it to .gitignore so it does not come back.",
    "vendor_dir": "Remove it from the archive and reinstall dependencies from the manifest (npm install / pip install -r requirements.txt).",
    "unused_asset": "Delete it if no page, stylesheet or script loads it (also check names built at run time).",
    "unused_module": "Confirm nothing loads it (entry points, plugin systems, build scripts), then delete the file.",
}
BETTER = {
    "unused_function": "Less code to read, test and maintain; the remaining code is what actually runs.",
    "unused_class": "Less code to read, test and maintain.",
    "unused_import": "Faster imports and a truthful list of what the file depends on.",
    "unused_variable": "The code now only contains values that influence the result.",
    "unused_export": "The public surface now matches what is really used.",
    "unreachable_code": "The block now contains only code that can run.",
    "dead_branch": "Only the branch that can run remains.",
    "junk_file": "Smaller, cleaner project.",
    "duplicate_file": "One source of truth for the content.",
    "vendor_dir": "Much smaller archive; dependencies stay reproducible from the manifest.",
    "unused_asset": "Smaller bundle.",
    "unused_module": "Less dead code to maintain.",
}


def risk_level(f) -> str:
    if f.fix_mode == "auto" and f.confidence >= 85 and f.certainty == "confirmed":
        return "Low"
    if f.confidence >= 60:
        return "Medium"
    return "High"


def fix_mode_text(mode: str) -> str:
    return {"auto": "Can be applied automatically (safe, verified by syntax check and backed up).",
            "review": "A fix can be generated, but a human must approve it because it may be used dynamically or has side effects.",
            "manual": "No safe automatic fix: needs manual review/refactoring."}.get(mode, "")


def build_details(f, lines, context: int, root=None) -> dict:
    cat = f.category
    d = {"label": CATEGORY_LABELS.get(cat, cat), "why": WHY.get(cat, ""), "evidence": list(f.evidence),
         "consequences": CONSEQUENCE.get(cat, ""), "recommendation": RECOMMEND.get(cat, ""), "why_better": BETTER.get(cat, ""),
         "risk": risk_level(f), "fix_text": fix_mode_text(f.fix_mode), "before": None, "after": None}
    certain = ("Confirmed: established directly from the code structure/search evidence above." if f.certainty == "confirmed"
               else "Potential: static analysis cannot be sure (dynamic use, public API or framework conventions are possible). Treat as a lead, not a verdict.")
    d["certainty_text"] = certain
    if f.item_type == "code" and f.plan and lines:
        before, after = preview_window(lines, f.plan, context)
        d["before"], d["after"] = before, after
        if f.fix_mode == "manual":
            d["after"] = None
    elif f.item_type == "code":
        d["before"] = f.snippet
        d["after"] = None
        if f.category == "duplicate_code":
            d["recommendation"] += " Other copies: " + ", ".join(f.extra.get("others", []))
    elif f.item_type in ("file", "dir"):
        d["before"] = f"{f.file}{'/' if f.item_type == 'dir' else ''}  ({f.size_bytes} bytes)"
        d["after"] = "(removed from the project)" if f.fix_mode != "manual" else None
        if f.extra.get("kind") == "duplicate":
            d["recommendation"] = f"Keep `{f.extra.get('original')}` and delete this copy after checking references."
    if cat == "unused_variable" and f.extra.get("how") == "keep_call":
        d["why_better"] = "The call (which may have side effects) is kept; only the useless variable is dropped."
    if cat == "unused_import" and f.extra.get("origin") != "stdlib":
        d["recommendation"] += " Be aware that importing a module can have side effects."
    d["validation"] = "Not applied yet. After applying, DeadCodeX re-parses the file (no code is executed) and records the result in the cleanup history."
    return d
