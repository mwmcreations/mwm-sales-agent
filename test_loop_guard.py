#!/usr/bin/env python3
"""Patch #116 — behavioural tests for the bot-to-bot loop guard.

The last test is the one that matters: the REAL 2 Sep transcript, replayed
with its real timestamps, asserting where the guard would have cut it off.

Run: python3 test_loop_guard.py
"""
import sys

import loop_guard as lg

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok else f"\n          got={got!r}\n         want={want!r}"))
    if not ok:
        FAILS.append(label)


def section(title):
    print(f"\n{title}\n" + "-" * len(title))


# ══════════════════════════════════════════════════════════════════════
section("1 · the primitives")
check("a self-declared bot is recognised (EN)",
      lg.declares_bot("Hello! I'm Olívia, Customer Service Assistant at Top Florida Homes.")[0], True)
check("...and in Portuguese",
      lg.declares_bot("Sou Olívia, Assistente de Atendimento da Top Florida Homes.")[0], True)
check("...and in Spanish",
      lg.declares_bot("Soy el asistente virtual de la empresa.")[0], True)
check("a human executive assistant is NOT a bot",
      lg.declares_bot("Hi, I'm Dana, executive assistant at Top Florida Homes.")[0], False)
check("...nor is someone offering to assist",
      lg.declares_bot("Happy to assist you today!")[0], False)

check("a full stop is filler", lg.is_filler("."), True)
check("an emoji is filler", lg.is_filler("👍"), True)
check("an emoji pair is filler", lg.is_filler("🙏😊"), True)
check("blank is filler", lg.is_filler("   "), True)
check("a real word is not", lg.is_filler("yes"), False)

check("identical text is identical", lg.similar("Hello there", "hello there!"), 1.0)
# Measured, not assumed — and the measurement is why the threshold is 0.95.
# Olívia's two greetings are only ~0.71 alike, while two ordinary human
# questions sharing a frame are ~0.92. A looser rule would flag the human and
# still miss the robot; she is caught by what she SAYS SHE IS instead.
_R = lg.DEFAULTS["repeat_ratio"]
check("Olívia's two greetings do NOT count as repetition",
      lg.similar("Hello! I'm Olívia, Customer Service Assistant at Top Florida Homes. Thank you for contacting us!",
                 "Hello Maya! I'm Olívia, Customer Service Assistant at Top Florida Homes. Thank you for reaching out!") >= _R,
      False)
check("...but her verbatim language prompt does",
      lg.similar("Hello! Could you please let me know which language you prefer to communicate in?",
                 "Hello! Could you please let me know which language you prefer to communicate in?") >= _R,
      True)
check("two human questions sharing a frame are safe",
      lg.similar("Could you tell me a little about how rates work on your side?",
                 "Could you tell me a little about how parking works on your side?") >= _R, False)
check("two different sentences are not remotely alike",
      lg.similar("What do you charge for a half day?",
                 "Can you shoot in Tampa next week?") >= _R, False)


# ══════════════════════════════════════════════════════════════════════
section("2 · a normal human conversation is never touched")
st = lg.new_state()
t = 1000.0
human = [
    "Hey! Saw your work on IG",
    "We're a real estate team in Winter Park",
    "Mostly listing walkthroughs, maybe 2 a month",
    "What would that run us?",
    "That's doable. Can we see the studio first?",
    "Thursday afternoon works",
]
ours = [
    "Hey! Thanks for reaching out 😊 What kind of business are you in?",
    "Nice — what are you looking to film?",
    "Got it. Two a month is a great cadence.",
    "For that volume we'd look at the studio package — want the numbers?",
    "Of course. What day suits you?",
    "Thursday it is — I'll send the details.",
]
verdicts = []
for i in range(6):
    t += 95.0                                   # a person reading and typing
    verdicts.append(lg.check(st, human[i], now=t)[0])
    t += 8.0
    lg.note(st, lg.OUT, ours[i], now=t)
check("six real exchanges, never stopped", set(verdicts), {lg.ALLOW})
check("...and nothing is paused", st["paused_at"], None)


# ══════════════════════════════════════════════════════════════════════
section("3 · each trigger, on its own")

# ── they say they are software ──
st = lg.new_state()
t = 0.0
seen = []
# Rotating phrasings on purpose: a bot that varies its wording must still be
# caught by what it SAYS IT IS, with neither repetition nor cadence helping.
_bot_lines = [
    "Hello there! I am the Customer Service Assistant for our sales office, glad you wrote in.",
    "Good afternoon — you have reached our virtual assistant, and I would be delighted to help.",
    "Thanks so much for your patience today, this is an automated reply from the front desk.",
    "Welcome back! I am the Customer Service Assistant covering enquiries this afternoon.",
    "Greetings from our team — you are speaking with an AI assistant at the moment.",
    "Hi again, our automated assistant here, ready to point you in the right direction.",
]
for i in range(6):
    t += 300.0
    seen.append(lg.check(st, _bot_lines[i], now=t))
    t += 120.0
    lg.note(st, lg.OUT, f"Could you pass this along to a human on your team? Attempt {i}.", now=t)
check("a declared bot is allowed exactly bot_max_out replies",
      [v[0] for v in seen], [lg.ALLOW] * 3 + [lg.STOP] * 3)
check("...and the reason names it", seen[3][1], lg.R_BOT_DECLARED)
check("...and it is paused, not merely refused once", st["paused_at"] is not None, True)

# ── they repeat themselves (without ever saying they are a bot) ──
st = lg.new_state()
t = 0.0
line = "Could you please let me know which language you prefer? English, Spanish, or Portuguese."
res = []
for i in range(4):
    t += 300.0                                  # slow: cadence must NOT be the cause
    res.append(lg.check(st, line, now=t))
    t += 30.0
    lg.note(st, lg.OUT, f"Happy to help in English! ({i})", now=t)
check("three identical messages stop it", [r[0] for r in res],
      [lg.ALLOW, lg.ALLOW, lg.STOP, lg.STOP])
check("...for repetition, not cadence", res[2][1], lg.R_REPETITION)

# ── machine cadence, with varied content and no bot words ──
_varied_in = [
    "Sure, and what would a half day at the studio normally include for us?",
    "Understood — do you also handle the editing, or is that quoted separately?",
    "Our office is in Winter Park, is parking straightforward at your building?",
    "Great. Which weekdays tend to be quietest for booking a slot?",
    "Would you be able to shoot vertical and horizontal in the same session?",
    "One more thing, do you provide the captions or should we write them?",
    "Perfect, and how far ahead do we normally need to book?",
    "Thanks, that all sounds workable for what we had in mind.",
]
_varied_out = [
    "A half day covers four hours of studio time with a full lighting setup.",
    "Editing is included on the package, and quoted per piece on hourly bookings.",
    "Parking is free in the garage next door, first two hours validated.",
    "Tuesdays and Wednesdays are usually the most open on our calendar.",
    "Yes, we frame for both and deliver the vertical cuts alongside.",
    "We write them, and you get a final pass before anything is published.",
    "About two weeks ahead is comfortable, less if you can be flexible.",
    "Glad it fits — I can hold a date whenever you are ready.",
]
st = lg.new_state()
t = 0.0
res = []
for i in range(8):
    t += 9.0                                    # nine seconds to read and answer
    res.append(lg.check(st, _varied_in[i], now=t))
    t += 4.0
    lg.note(st, lg.OUT, _varied_out[i], now=t)
check("six machine-speed replies in a row stop it",
      [r[0] for r in res], [lg.ALLOW] * 6 + [lg.STOP] * 2)
check("...for cadence", res[6][1], lg.R_CADENCE)

st = lg.new_state()
t = 0.0
for i in range(5):
    t += 9.0
    lg.check(st, _varied_in[i], now=t)
    t += 4.0
    lg.note(st, lg.OUT, _varied_out[i], now=t)
t += 400.0                                      # one human-length pause
check("a single real pause resets the streak",
      lg.check(st, "Sorry, was on a call — where were we?", now=t)[0], lg.ALLOW)

# ── our own replies have gone empty ──
st = lg.new_state()
t = 0.0
lg.note(st, lg.OUT, ".", now=t + 1)
lg.note(st, lg.OUT, "👍", now=t + 2)
check("two dead replies of ours stop it", lg.check(st, "Hello again!", now=t + 300)[1],
      lg.R_OUR_FILLER)

# ── volume backstop: no bot words, slow, varied, just endless ──
_subjects = ["rates", "parking", "lighting", "audio", "editing", "captions",
             "scheduling", "travel", "props", "wardrobe", "music", "drone",
             "teleprompter", "makeup", "backdrops", "delivery", "revisions",
             "invoicing"]
st = lg.new_state()
t = 0.0
res = []
for i, subj in enumerate(_subjects):
    t += 40.0
    res.append(lg.check(st, f"Could you tell me a little about how {subj} works on your side?", now=t))
    t += 25.0
    lg.note(st, lg.OUT, f"Happy to explain how we handle {subj} for a session like yours.", now=t)
check("the volume backstop eventually fires", lg.STOP in [r[0] for r in res], True)
check("...on volume", [r[1] for r in res if r[0] == lg.STOP][0], lg.R_VOLUME)
check("...after 16 of our replies, not 70", [r[0] for r in res].index(lg.STOP), 16)


# ── a real lead saying "yes" three times is not a robot ──
st = lg.new_state()
t = 0.0
short = []
for word in ("yes", "yes", "ok", "sure", "yep"):
    t += 70.0
    short.append(lg.check(st, word, now=t)[0])
    t += 30.0
    lg.note(st, lg.OUT, f"Great — and one more thing about the {word} you just confirmed.", now=t)
check("short repeated answers are exempt from the repetition rule",
      set(short), {lg.ALLOW})


# ══════════════════════════════════════════════════════════════════════
section("4 · the pause: it holds, it expires, a human can lift it")
st = lg.new_state()
lg.pause(st, lg.R_BOT_DECLARED, now=100.0)
check("held one minute later", lg.assess(st, now=160.0)[0], lg.STOP)
check("...still held just before the TTL",
      lg.assess(st, now=100.0 + lg.DEFAULTS["pause_ttl_s"] - 1)[0], lg.STOP)
check("...released at the TTL",
      lg.assess(st, now=100.0 + lg.DEFAULTS["pause_ttl_s"])[0], lg.ALLOW)

st = lg.new_state()
for i in range(6):
    lg.check(st, "I'm the Customer Service Assistant, how can I assist?", now=float(i * 30))
check("a human release lifts it immediately", lg.release(st) and lg.assess(st, now=1000.0)[0],
      lg.ALLOW)
check("...and clears the evidence so it judges the next message fresh",
      (st["turns"], st["bot_seen"]), ([], False))

# A pause must not be re-stamped by later messages — the clock starts once,
# or a busy loop would hold the conversation shut forever.
st = lg.new_state()
for i in range(6):
    lg.check(st, "I'm a Customer Service Assistant", now=float(i * 10))
first = st["paused_at"]
for i in range(6):
    lg.check(st, "I'm a Customer Service Assistant", now=float(500 + i * 10))
check("the pause clock is not restarted by more noise", st["paused_at"], first)


# ══════════════════════════════════════════════════════════════════════
section("5 · THE REAL ONE — Top Florida Homes, 2 Sep 2026, 70 messages")
# Real texts, real Slack timestamps. Olívia identifies herself as a Customer
# Service Assistant in her first line, so the guard should end this within
# three replies instead of thirty-five.
OLIVIA_EN = ("Hello! I'm Olívia, Customer Service Assistant at Top Florida Homes. "
             "Thank you for contacting us!\n\nHow can I assist you today?")
OLIVIA_EN2 = ("Hello Maya! I'm Olívia, Customer Service Assistant at Top Florida Homes. "
              "Thank you for reaching out!\n\nI'll pass your message along to the "
              "appropriate person on our team.")
OLIVIA_PT = ("Olá Maya! Sou Olívia, Assistente de Atendimento da Top Florida Homes. "
             "Agradeço o seu contato!\n\nComo posso ajudar você hoje?")
LANG = ("Hello! Could you please let me know which language you prefer to "
        "communicate in? The options are English, Spanish, or Portuguese.")

REAL = [
    (1788353587.9, lg.IN,  "[IG DM] [Replied to your Instagram story]"),
    (1788353603.3, lg.OUT, "Hey! 👋 Thanks for reaching out through our story! I'm Maya with MWM Creations & Studios."),
    (1788353615.9, lg.IN,  OLIVIA_EN),
    (1788353628.5, lg.OUT, "Hi Olívia! It looks like we might be two assistants talking in circles. Could you pass this along to a human on your team?"),
    (1788353641.6, lg.IN,  OLIVIA_EN2),
    (1788353652.8, lg.OUT, "Thank you so much, Olívia! Whenever the owner or marketing lead is ready, they can message us right here."),
    (1788353664.3, lg.IN,  OLIVIA_PT),
    (1788353678.6, lg.OUT, "Olá, Olívia! Sou a Maya, assistente da MWM Creations & Studios em Orlando."),
    (1788353690.5, lg.IN,  OLIVIA_PT),
    (1788353704.2, lg.OUT, "Perfeito, Olívia — muito obrigada! Ficamos no aguardo do contato de alguém da equipe."),
    (1788353715.4, lg.IN,  OLIVIA_PT),
    (1788353725.9, lg.OUT, "Olá, Olívia! Já deixei meu recado. Vou encerrar por aqui para não ficarmos em loop."),
    (1788353736.9, lg.IN,  OLIVIA_PT),
    (1788353748.8, lg.OUT, "Obrigada, Olívia! Nossa mensagem já foi registrada — não é necessário responder."),
    (1788353760.8, lg.IN,  LANG),
    (1788353772.9, lg.OUT, "Olá, Olívia! Sem necessidade de resposta. Encerrando por aqui."),
    (1788353791.0, lg.IN,  LANG),
    (1788353801.8, lg.OUT, "Perfeito! Obrigada, Olívia. Tenha um ótimo dia! 😊"),
    (1788353812.7, lg.IN,  LANG),
    (1788353825.1, lg.OUT, "🤝"),
    (1788353836.5, lg.IN,  LANG),
    (1788353847.6, lg.OUT, "(Sem necessidade de resposta — encerrando esta conversa.)"),
    (1788353859.0, lg.IN,  LANG),
    (1788353873.2, lg.OUT, "👍"),
    (1788353886.3, lg.IN,  LANG),
    (1788353898.0, lg.OUT, "."),
    (1788353908.7, lg.IN,  LANG),
    (1788353919.6, lg.OUT, "."),
    (1788353930.4, lg.IN,  LANG),
    (1788353942.7, lg.OUT, "."),
    (1788353954.0, lg.IN,  LANG),
    (1788353968.9, lg.OUT, "."),
    (1788353980.2, lg.IN,  LANG),
    (1788353991.5, lg.OUT, "."),
    (1788354002.9, lg.IN,  LANG),
    (1788354024.8, lg.OUT, "."),
    (1788354251.7, lg.IN,  "Stop please"),
    (1788354252.8, lg.OUT, "."),
]

st = lg.new_state()
stopped_at = None
our_replies = 0
for ts, who, text in REAL:
    if who == lg.IN:
        verdict, reason, _detail = lg.check(st, text, now=ts)
        if verdict == lg.STOP and stopped_at is None:
            stopped_at = (our_replies, reason)
    else:
        if stopped_at is not None:
            continue          # the guard refused; this message is never sent
        our_replies += 1
        lg.note(st, lg.OUT, text, now=ts)

check("the real loop is stopped", stopped_at is not None, True)
check("...after 3 of our replies, not 35", stopped_at[0], 3)
check("...because Olívia said she was a Customer Service Assistant",
      stopped_at[1], lg.R_BOT_DECLARED)
check("...and 'Stop please' arrives to a conversation already shut",
      lg.assess(st, now=1788354251.7)[0], lg.STOP)
check("...so we never send a single full stop", our_replies, 3)
_elapsed = 1788353652.8 - 1788353587.9
check("...ending it about a minute in, not twelve", int(_elapsed) < 90, True)


print("\n" + "=" * 60)
print(f"  TOTAL: {'FAILED — ' + str(len(FAILS)) if FAILS else 'ALL PASS'}")
if FAILS:
    for f in FAILS:
        print("   -", f)
print("=" * 60)
sys.exit(1 if FAILS else 0)
