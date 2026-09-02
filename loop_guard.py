"""Loop guard — stop Maya talking to another company's robot.

PATCH #116.

2 Sep 2026, 08:53–09:05 ET: an Instagram DM thread with "Olívia, Customer
Service Assistant at Top Florida Homes" ran to **70 messages in twelve
minutes**, roughly one exchange every eleven seconds. Maya recognised it —
she wrote "Loop de automação detectado — encerrando o atendimento" — and then
sent thirty more messages, most of them a single full stop, because the model
saying "I am ending this" is not the same thing as the code stopping. The other
robot even sent "Stop please". We answered that with "." too.

That is the lesson this module exists for: **a polite goodbye is not a
circuit breaker.** The stop has to be mechanical, it has to live outside the
model, and it has to be able to refuse to call the model at all.

Pure logic, no I/O, no imports beyond the standard library, so the whole thing
is testable without a webhook. The caller owns the state dict and decides where
it is persisted; a pause that lives only in RAM comes back after a deploy and
the loop resumes, so the caller should persist it.

WHAT TRIPS IT (any one is enough — they catch different failures):

  1. THEY SAY THEY ARE A ROBOT. "Customer Service Assistant",
     "assistente de atendimento", "virtual assistant", "automated reply".
     Olívia said this in her FIRST message. Asking a robot to fetch a human is
     worth a try or two, and no more — so after `bot_max_out` of our replies we
     stop. This alone would have ended the real incident at reply 3 of 35.

  2. THEY REPEAT THEMSELVES. Three near-identical messages inside their last
     five. A person does not send the same sentence three times; a script sends
     nothing else. Near-identical, not identical: Olívia alternated "Thank you
     for contacting us" with "Thank you for reaching out".
     SHORT ANSWERS ARE EXEMPT (`repeat_min_words`). A real lead answering
     "yes", "yes", "ok" is the most ordinary thing on this channel, and
     counting that as robotic would shut off the good conversations to fix
     the bad ones.
     The threshold is 0.95 — near-VERBATIM — and that number was measured,
     not guessed. On the real transcript, Olívia's two English greetings score
     0.71 and her two Portuguese ones 0.67, while two ordinary human questions
     sharing a frame ("Could you tell me about how X works on your side?")
     score 0.92. A looser threshold would therefore have flagged the human and
     STILL missed the robot. What actually repeats verbatim is her language
     prompt, sent word-for-word more than a dozen times — and that is what
     this rule is for. Olívia herself is caught by rule 1, not this one.

  3. MACHINE CADENCE. Six consecutive replies that came back faster than a
     person can read and type. Slow on its own — a human CAN fire off six quick
     one-word answers — which is why it needs six in a row.

  4. WE HAVE RUN OUT OF WORDS. Two of our own replies in a row that are a full
     stop, a thumbs-up or an empty string. When Maya is reduced to punctuation
     the conversation is over whatever the other side does.

  5. SHEER VOLUME. A backstop for a shape nobody predicted: more than
     `max_out` of our messages inside `window_s`.

WHAT IT DOES NOT DO: it never sends anything, never edits history, and never
decides what a human should do about it. It answers one question — may we
reply to this conversation right now — and says why not.
"""

import difflib
import re
import time

# ── the shape of a decision ────────────────────────────────────────────
ALLOW = "allow"
STOP = "stop"

# Reasons, as constants so a caller can branch on them and a test can assert
# them without matching prose.
R_BOT_DECLARED = "bot_declared"
R_REPETITION = "repetition"
R_CADENCE = "cadence"
R_OUR_FILLER = "our_filler"
R_VOLUME = "volume"
R_PAUSED = "already_paused"

IN = "in"
OUT = "out"

DEFAULTS = {
    "bot_max_out": 3,        # replies allowed once they declare themselves a robot
    "repeat_window": 5,      # how many of their recent messages we look at
    "repeat_hits": 3,        # how many of those must be near-identical
    "repeat_ratio": 0.95,    # what "near-identical" means — see the note below
    "repeat_min_words": 5,   # ...and short answers are exempt entirely
    "fast_s": 20.0,          # a reply this quick is not a person reading
    "fast_streak": 6,        # ...and it takes this many in a row to count
    "filler_streak": 2,      # our own dead replies in a row
    "max_out": 16,           # backstop volume cap
    "window_s": 1800.0,      # ...measured over this window
    "pause_ttl_s": 86400.0,  # how long a tripped conversation stays shut
    "keep_turns": 40,        # ring buffer; nothing here needs deep history
}

# Phrases in which the other side tells us, in so many words, that it is
# software. Deliberately NOT bare "assistant at": real people are executive
# assistants and admin assistants, and capping a real lead at three replies
# because of their job title is a worse bug than the one being fixed.
BOT_PHRASES = (
    # English
    "customer service assistant", "virtual assistant", "automated assistant",
    "ai assistant", "automated reply", "automatic reply", "auto-reply",
    "this is an automated", "i am a bot", "i'm a bot", "chatbot",
    "i am an ai", "i'm an ai",
    # Portuguese
    "assistente de atendimento", "assistente virtual", "resposta automática",
    "resposta automatica", "atendimento automático", "atendimento automatico",
    "sou um bot", "sou uma ia",
    # Spanish
    "asistente virtual", "asistente de atención", "asistente de atencion",
    "respuesta automática", "respuesta automatica", "soy un bot",
)

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+", re.UNICODE)

# What our own side looks like when it has nothing left to say. The real
# incident produced dozens of these.
_FILLER_EXACT = {"", ".", "..", "...", "-", "ok", "okay", "k"}


def normalize(text):
    """Casefolded, punctuation- and emoji-stripped, whitespace-collapsed."""
    out = _NON_WORD.sub(" ", str(text or ""))
    return _SPACES.sub(" ", out).strip().casefold()


def is_filler(text):
    """True when a message carries no content — punctuation, an emoji, blank.

    Emoji strip to nothing under `normalize`, which is exactly the signal: a
    reply that survives normalisation as an empty string said nothing.
    """
    raw = str(text or "").strip()
    if raw.casefold() in _FILLER_EXACT:
        return True
    return normalize(raw) == ""


def declares_bot(text):
    """(True, phrase) when the text says outright that it is software."""
    low = " " + normalize(text) + " "
    for phrase in BOT_PHRASES:
        if normalize(phrase) in low:
            return True, phrase
    return False, ""


def similar(a, b):
    """0..1 similarity of two normalised messages."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 1.0 if na == nb else 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def new_state():
    return {"turns": [], "paused_at": None, "paused_reason": "", "bot_seen": False}


def note(state, who, text, now=None, cfg=None):
    """Record one turn. `who` is loop_guard.IN or loop_guard.OUT."""
    cfg = _cfg(cfg)
    now = float(now if now is not None else time.time())
    turns = state.setdefault("turns", [])
    turns.append({"who": who, "t": now, "text": str(text or "")})
    if who == IN and not state.get("bot_seen"):
        hit, _phrase = declares_bot(text)
        if hit:
            state["bot_seen"] = True
    keep = int(cfg["keep_turns"])
    if len(turns) > keep:
        del turns[:-keep]
    return state


def pause(state, reason, now=None):
    state["paused_at"] = float(now if now is not None else time.time())
    state["paused_reason"] = str(reason or "")
    return state


def release(state):
    """A human took it back. Clears the pause AND the evidence, so the guard
    judges what happens next on its own merits rather than re-tripping on
    the argument it already had."""
    state["paused_at"] = None
    state["paused_reason"] = ""
    state["bot_seen"] = False
    state["turns"] = []
    return state


def paused(state, now=None, cfg=None):
    """(True, reason) while the pause stands. Expiry re-arms the guard: the
    turns are cleared so a stale argument cannot re-trip it instantly."""
    cfg = _cfg(cfg)
    at = state.get("paused_at")
    if not at:
        return False, ""
    now = float(now if now is not None else time.time())
    if now - float(at) >= float(cfg["pause_ttl_s"]):
        release(state)
        return False, ""
    return True, str(state.get("paused_reason") or R_PAUSED)


def _cfg(cfg):
    merged = dict(DEFAULTS)
    for key, val in (cfg or {}).items():
        if key in merged and val is not None:
            merged[key] = val
    return merged


def _outs(state):
    return [t for t in state.get("turns", []) if t.get("who") == OUT]


def _ins(state):
    return [t for t in state.get("turns", []) if t.get("who") == IN]


def _reply_gaps(state):
    """How long THEY took to answer each of our messages, oldest first.

    Their speed is the signal about them; ours says nothing. Pair each OUT with
    the first IN that follows it, and ignore an OUT nobody answered.
    """
    gaps = []
    pending_out_t = None
    for turn in state.get("turns", []):
        who = turn.get("who")
        when = float(turn.get("t") or 0)
        if who == OUT:
            pending_out_t = when
        elif who == IN and pending_out_t is not None:
            gaps.append(when - pending_out_t)
            pending_out_t = None
    return gaps


def _fast_streak(state, cfg):
    """The run of their most recent replies that came back faster than a
    person could read ours. Counted backwards, so a single human-length pause
    resets it — which is what keeps a chatty but real lead out of this."""
    streak = 0
    for gap in reversed(_reply_gaps(state)):
        if abs(gap) <= float(cfg["fast_s"]):
            streak += 1
            continue
        break
    return streak


def assess(state, now=None, cfg=None):
    """(verdict, reason, detail) — may we send an automated reply right now?

    Call it BEFORE building the reply. Refusing here saves the model call as
    well as the message, and a guard that runs after generation is a guard
    that has already paid for the thing it is preventing.
    """
    cfg = _cfg(cfg)
    now = float(now if now is not None else time.time())

    is_paused, why = paused(state, now=now, cfg=cfg)
    if is_paused:
        return STOP, why, "conversation is paused"

    outs = _outs(state)
    ins = _ins(state)

    # 1 · they told us they are software
    if state.get("bot_seen") and len(outs) >= int(cfg["bot_max_out"]):
        return (STOP, R_BOT_DECLARED,
                "the other side identifies as an automated assistant and we "
                "have already sent {} replies".format(len(outs)))

    # 2 · they repeat themselves
    min_words = int(cfg["repeat_min_words"])
    recent = [t for t in ins[-int(cfg["repeat_window"]):]
              if len(normalize(t.get("text")).split()) >= min_words]
    for i, turn in enumerate(recent):
        hits = 1 + sum(1 for other in recent[i + 1:]
                       if similar(turn.get("text"), other.get("text")) >= float(cfg["repeat_ratio"]))
        if hits >= int(cfg["repeat_hits"]):
            return (STOP, R_REPETITION,
                    "{} near-identical messages from them in the last {}".format(
                        hits, len(ins[-int(cfg["repeat_window"]):])))

    # 3 · machine cadence
    streak = _fast_streak(state, cfg)
    if streak >= int(cfg["fast_streak"]):
        return (STOP, R_CADENCE,
                "{} consecutive replies inside {:.0f}s".format(streak, cfg["fast_s"]))

    # 4 · our own replies have gone empty
    tail = outs[-int(cfg["filler_streak"]):]
    if len(tail) >= int(cfg["filler_streak"]) and all(is_filler(t.get("text")) for t in tail):
        return (STOP, R_OUR_FILLER,
                "our last {} replies said nothing".format(len(tail)))

    # 5 · volume backstop
    window = [t for t in outs if now - float(t.get("t") or 0) <= float(cfg["window_s"])]
    if len(window) >= int(cfg["max_out"]):
        return (STOP, R_VOLUME,
                "{} replies inside {:.0f} minutes".format(len(window), cfg["window_s"] / 60.0))

    return ALLOW, "", ""


def check(state, inbound_text, now=None, cfg=None):
    """The one call a webhook needs: record their message, then rule on it.

    Returns (verdict, reason, detail). On STOP the caller must not generate or
    send anything, and — the half that is easy to forget — must tell a human,
    because a conversation that stops silently is indistinguishable from one
    that was never received.
    """
    note(state, IN, inbound_text, now=now, cfg=cfg)
    verdict, reason, detail = assess(state, now=now, cfg=cfg)
    if verdict == STOP and not state.get("paused_at"):
        pause(state, reason, now=now)
    return verdict, reason, detail
