"""Optional browser smoke test (needs: pip install playwright; playwright install chromium).
Run: python tests/browser_smoke.py - starts a temporary server on port 5055 and drives the real UI."""
import sys, io, zipfile, subprocess, time, os, tempfile, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path[:0] = [ROOT, os.path.join(ROOT, 'tests')]
from conftest import SAMPLE, make_zip
from playwright.sync_api import sync_playwright
d = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_URL="sqlite:///" + d + "/s.db", FLASK_APP="app")
code = f"""
import sys; sys.path.insert(0,{ROOT!r})
from deadcodex import create_app
app=create_app({{'INSTANCE_PATH':'{d}/inst','SQLALCHEMY_DATABASE_URI':'sqlite:///{d}/s.db'}})
app.run(port=5055)
"""
srv = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)
zp = d + "/p.zip"; open(zp, "wb").write(make_zip(SAMPLE))
errors = []
try:
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        pg.on("pageerror", lambda e: errors.append(("pageerror", str(e))))
        pg.on("console", lambda m: errors.append(("console", m.text)) if m.type == "error" and "ERR_" not in m.text and "Failed to load resource" not in m.text else None)
        B = "http://127.0.0.1:5055"
        pg.goto(B + "/register"); pg.fill("[name=username]", "pwuser"); pg.fill("[name=email]", "pw@example.com"); pg.fill("[name=password]", "password123")
        pg.click("button[type=submit]"); pg.wait_for_url("**/dashboard")
        pg.goto(B + "/upload"); pg.set_input_files("input[type=file]", zp)
        pg.fill("[name=project_name]", "PW") if pg.query_selector("[name=project_name]") else None
        pg.click("form[enctype] button[type=submit], form[enctype] button") ; pg.wait_for_url("**/analysis/*", timeout=15000)
        pg.wait_for_load_state("load")
        pg.wait_for_function("document.body && document.body.innerText.includes('never_called_function')", timeout=20000)
        print("analysis findings rendered")
        sid = pg.url.rstrip("/").split("/")[-1]
        for path in [f"/project/{sid}", f"/rectifier/{sid}", "/settings", "/docs", "/dashboard"]:
            pg.goto(B + path); pg.wait_for_timeout(400); print("ok", path)
        pg.goto(B + f"/cleanup/{sid}"); pg.wait_for_selector("#items input[type=checkbox]", timeout=10000)
        pg.click("#select-all"); pg.wait_for_timeout(800)
        print("selected:", pg.inner_text("#selected-count"), "| pct:", pg.inner_text("#pct"))
        pg.click("#clean-btn"); pg.wait_for_selector("#go", timeout=10000); pg.click("#go")
        pg.wait_for_url("**/cleanup/*", timeout=20000); pg.wait_for_selector("text=Run #1", timeout=20000)
        print("history shows run; rollback button:", pg.query_selector(".rollback") is not None)
        pg.on("dialog", lambda dlg: dlg.accept())
        pg.click("details summary"); pg.click(".rollback"); pg.wait_for_selector("text=Rolled back", timeout=20000); print("rolled back via UI")
        b.close()
finally:
    srv.terminate()
print("JS ERRORS:", errors)
