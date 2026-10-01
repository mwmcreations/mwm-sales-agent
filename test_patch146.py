"""PATCH #146 gate — Twilio inbound routing repair (/admin/sms-inbound-config).

Lifts the pure function out of app.py with AST (no Flask, no network) and
drives it with a fake Twilio. Prints "N passed, M failed".
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()

WANT = ["sms_inbound_config", "_sms_inbound_service_view", "_sms_inbound_number_view"]
tree = ast.parse(SRC)
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in WANT]
mod = ast.Module(body=nodes, type_ignores=[])
ns = {
    "TWILIO_ACCOUNT_SID": "ACxxx", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_MESSAGING_SERVICE_SID": "MGabc",
    "SMS_INBOUND_WEBHOOK_URL": "https://mwm-sales-agent-production.up.railway.app/webhook/sms-inbound",
    "_TWILIO_MSG_API": "https://messaging.twilio.com/v1",
    "_TWILIO_REST_API": "https://api.twilio.com/2010-04-01",
    "_twilio_call": lambda *a, **k: (0, {"error": "network disabled in test"}),
}
exec(compile(mod, "app_lifted", "exec"), ns)
sms_inbound_config = ns["sms_inbound_config"]

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


class FakeTwilio:
    def __init__(self, inbound_url="", use_on_number=False, numbers=None, sms_url=""):
        self.svc = {"sid": "MGabc", "friendly_name": "MWM", "inbound_request_url": inbound_url,
                    "inbound_method": "POST", "fallback_url": None,
                    "use_inbound_webhook_on_number": use_on_number}
        self.numbers = {sid: {"sid": sid, "phone_number": pn, "sms_url": sms_url, "sms_method": "POST",
                              "sms_fallback_url": ""} for sid, pn in (numbers or [])}
        self.calls = []

    def __call__(self, method, url, data=None):
        self.calls.append((method, url, dict(data or {})))
        if url.endswith("/PhoneNumbers"):
            return 200, {"phone_numbers": [{"sid": s, "phone_number": n["phone_number"]} for s, n in self.numbers.items()]}
        if "/IncomingPhoneNumbers/" in url:
            sid = url.rsplit("/", 1)[1].replace(".json", "")
            num = self.numbers.get(sid)
            if not num:
                return 404, {"message": "no such number"}
            if method == "POST":
                num["sms_url"] = data.get("SmsUrl", num["sms_url"])
                num["sms_method"] = data.get("SmsMethod", num["sms_method"])
            return 200, dict(num)
        if url.endswith("/Services/MGabc"):
            if method == "POST":
                self.svc["inbound_request_url"] = data.get("InboundRequestUrl", self.svc["inbound_request_url"])
                self.svc["inbound_method"] = data.get("InboundMethod", self.svc["inbound_method"])
                self.svc["use_inbound_webhook_on_number"] = data.get("UseInboundWebhookOnNumber", "false") == "true"
            return 200, dict(self.svc)
        return 404, {"message": "unknown url"}


WANT_URL = ns["SMS_INBOUND_WEBHOOK_URL"]

# 1. inspect only — wrong URL is reported, nothing is written
fake = FakeTwilio(inbound_url="", numbers=[("PN1", "+14078716473")], sms_url="https://old.example/sms")
rep = sms_inbound_config(False, call=fake)
check("inspect.before_url_empty", rep["service"]["before"]["inbound_request_url"] == "")
check("inspect.correct_before_false", rep["service"]["correct_before"] is False)
check("inspect.no_apply_key", "apply" not in rep["service"])
check("inspect.no_posts", all(m == "GET" for m, _, _ in fake.calls), str(fake.calls))
check("inspect.number_seen", rep["numbers"] and rep["numbers"][0]["before"]["sms_url"] == "https://old.example/sms")
check("inspect.number_not_changed", "apply" not in rep["numbers"][0])

# 2. apply — service and number are pointed at the webhook, 'after' proves it
fake = FakeTwilio(inbound_url="https://wrong.example/x", use_on_number=True,
                  numbers=[("PN1", "+14078716473")], sms_url="")
rep = sms_inbound_config(True, call=fake)
posts = [(u, d) for m, u, d in fake.calls if m == "POST"]
check("apply.service_post", any(u.endswith("/Services/MGabc") and d.get("InboundRequestUrl") == WANT_URL
                                and d.get("InboundMethod") == "POST" and d.get("UseInboundWebhookOnNumber") == "false"
                                for u, d in posts), str(posts))
check("apply.after_url", rep["service"].get("after", {}).get("inbound_request_url") == WANT_URL)
check("apply.after_not_on_number", rep["service"].get("after", {}).get("use_inbound_webhook_on_number") is False)
check("apply.number_post", any("/IncomingPhoneNumbers/PN1.json" in u and d.get("SmsUrl") == WANT_URL for u, d in posts), str(posts))
check("apply.number_result", rep["numbers"][0].get("apply", {}).get("result", {}).get("sms_url") == WANT_URL)

# 3. already correct — apply writes nothing
fake = FakeTwilio(inbound_url=WANT_URL, numbers=[("PN1", "+14078716473")], sms_url=WANT_URL)
rep = sms_inbound_config(True, call=fake)
check("correct.flag", rep["service"]["correct_before"] is True)
check("correct.no_posts", all(m == "GET" for m, _, _ in fake.calls), str(fake.calls))

# 4. custom url override
fake = FakeTwilio(inbound_url="", numbers=[])
rep = sms_inbound_config(True, want_url="https://example.test/hook", call=fake)
check("override.url", rep["service"]["after"]["inbound_request_url"] == "https://example.test/hook")

# 5. missing credentials — says so, calls nothing
ns2 = dict(ns); ns2["TWILIO_MESSAGING_SERVICE_SID"] = ""
exec(compile(mod, "app_lifted2", "exec"), ns2)
fake = FakeTwilio()
rep = ns2["sms_inbound_config"](True, call=fake)
check("nocreds.note", "not all set" in rep["note"])
check("nocreds.no_calls", fake.calls == [])

# 6. the output never carries the credentials
import json
fake = FakeTwilio(inbound_url="", numbers=[("PN1", "+1")])
rep = sms_inbound_config(True, call=fake)
blob = json.dumps(rep)
check("no_secret_in_output", "tok" not in blob.split('"')[1::2] and "ACxxx" not in blob.replace("/Accounts/ACxxx", ""))

# 7. static: the route and the admin gate are wired
check("static.route", '@app.route("/admin/sms-inbound-config", methods=["GET", "POST"])' in SRC)
check("static.gate", 'def admin_sms_inbound_config():' in SRC and '_admin_secret_ok(request.values.get("secret", ""))' in SRC)
check("static.tally", '_TALLY.bump("sms.inbound_config"' in SRC)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
