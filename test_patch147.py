"""PATCH #147 gate — Maya books SMS leads with what the form already gave.

Michael's live test (Oct 1, 08:57–09:02 ET): after "Mon oct 5" Maya asked for
"full name, email, and business name" although the form lead carried all
three. Two causes: the SMS lead context never included the email, and the
channel rule did not say to book with known fields. Prints "N passed, M failed".
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()

tree = ast.parse(SRC)
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_sms_lead_context"]
ns = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "app_lifted", "exec"), ns)
ctx = ns["_sms_lead_context"]

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


rec = {"name": "Ana Lima", "email": "ana@example.com", "business": "Lima Dental",
       "role_raw": "Owner", "revenue_raw": "$50-150K", "qualified": "yes", "qualified_reason": "owner, 50K+",
       "source": "meta_lead_form"}
out = ctx(rec)
check("ctx.name", "Name: Ana Lima" in out)
check("ctx.email", "Email: ana@example.com" in out, out)
check("ctx.business", "Business: Lima Dental" in out)
check("ctx.order", out.index("Name:") < out.index("Email:") < out.index("Business:"))
check("ctx.no_email_when_missing", "Email:" not in ctx({"name": "X"}))
check("ctx.empty_ok", ctx(None) == "" and ctx({}) == "")

# the channel rule says: book with what the form gave, ask only for what is missing
i = SRC.index("--- CHANNEL: SMS (TEXT MESSAGE) ---")
rule = SRC[i:i + 2000]
check("rule.book_with_context", "book with those" in rule and "never ask the lead to" in rule, rule[:400])
check("rule.only_missing", "Ask only for a field that is missing" in rule)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
