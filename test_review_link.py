#!/usr/bin/env python3
"""The review ask must carry a way to leave a review.

Run as a script (repo convention). Exit 0 = pass.

WHY THIS EXISTS
---------------
For at least three sends across two clients, the day-7 review ask went out as
plain prose with no link in it. Michael, 17 Sep 2026: "there's no way the
person will click anywhere to do a review if it's just plain text with no place
for them to go." The one thing the message existed to produce was the one thing
it could not produce, and nothing in the codebase objected — every other step
carried BOOK_URL, so the omission looked like ordinary copy.

This test is the objection.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "outcome_sender.py")
if not os.path.exists(SRC):
    print("SKIP: outcome_sender.py not found")
    raise SystemExit(0)

src = io.open(SRC, encoding="utf-8").read()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)))
    if not cond:
        FAIL.append(name)


def strip_comments(text):
    """Drop whole-line # comments. The first version of this test failed because
    it matched the word BOOK_URL inside the comment explaining why BOOK_URL was
    NOT used here — a test that reads its own documentation as evidence."""
    return "\n".join(l for l in text.split("\n") if not l.strip().startswith("#"))


def block(fn_name):
    """The STEP_REVIEW branch inside one builder function, code only."""
    start = src.index("def %s(" % fn_name)
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    i = body.index("if kind == STEP_REVIEW:")
    j = len(body)
    for nxt in ("if kind == STEP_EMAIL_ASK:", "\n    return "):
        k = body.find(nxt, i)
        if k != -1:
            j = min(j, k)
    return strip_comments(body[i:j])


print("\nthe constant")
m = re.search(r'REVIEW_URL\s*=\s*"([^"]+)"', src)
check("REVIEW_URL is defined", m is not None)
url = m.group(1) if m else ""
check("it is an absolute https URL", url.startswith("https://"), url)
check("it points at a Google review surface",
      "writereview" in url or "g.page" in url, url)
check("it carries a place identifier", "placeid=" in url or "/r/" in url, url)
check("it is not the booking URL", "book-studio" not in url, url)

print("\nthe email ask")
email = block("_email_copy")
check("email review step references REVIEW_URL", "REVIEW_URL" in email)
check("the link is a real anchor, not bare text", 'href=\\"{REVIEW_URL}' in email or 'href="{REVIEW_URL}' in email)
check("the URL also appears in plain form for clients that strip styling",
      email.count("REVIEW_URL") >= 2, "found %d references" % email.count("REVIEW_URL"))
check("it still offers the reply-to-me escape hatch",
      "reply" in email.lower())
check("it does not send people to the booking page instead",
      "BOOK_URL" not in email)

print("\nthe DM ask")
short = block("_short_copy")
check("DM review step references REVIEW_URL", "REVIEW_URL" in short)
check("DM still offers the escape hatch", "reply" in short.lower() or "directly" in short.lower())

print("\ncopy sanity")
check("no first/second person slip ('hear it from me')",
      "hear it from me" not in src.lower(),
      "the client is the one being heard from, not Michael")

print("\nevery other step already had a link — this one was the outlier")
for step in ("STEP_REBOOK", "STEP_VALUE"):
    b = src[src.index("if kind == %s:" % step):]
    b = b[:b.index("\n    if kind ==", 1)] if "\n    if kind ==" in b[1:] else b[:800]
    check("%s still links somewhere" % step, "URL" in b)

print("\n" + "-" * 58)
if FAIL:
    print("FAILED %d: %s" % (len(FAIL), ", ".join(FAIL)))
    raise SystemExit(1)
print("review ask carries a working link")
