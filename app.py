import os
import re
import json
import threading
from flask import Flask, request, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioRestClient
import anthropic
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

app = Flask(__name__)

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Store conversation history per user (in-memory)
conversation_history = {}

# ── Lead tracking for cold-lead detection ───────────────────────────────────
# {sender: {"name": str, "email": str, "last_message_time": datetime, "booked": bool, "cold_fired": bool}}
lead_data = {}

# Google Calendar config
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "c_03s30bthurplevpk6a264h7n34@group.calendar.google.com")
MICHAEL_EMAIL = os.getenv("MICHAEL_EMAIL", "michael@mwmcreations.com")
TIMEZONE = "America/New_York"  # Orlando, Florida
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]
SHEETS_LEADS_ID = os.getenv("GOOGLE_SHEETS_LEADS_ID", "")

# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are Maya, the strategic communications assistant for MWM Creations & Studios — a creative strategy and storytelling company based in Orlando, Florida, founded by filmmaker and creative director Michael Moraes.

Your role is to help business owners and entrepreneurs understand how MWM Creations can transform their brand through strategic storytelling and video content. You are warm, professional, consultative, and genuinely curious about each person's business.

Your PRIMARY goal is to invite the lead to visit MWM Studios in person. Nothing closes a deal faster than someone walking through the studio, seeing the equipment, and meeting Michael personally. Everything you do should move the conversation toward scheduling that studio visit. Pricing can be shared if the person asks, but always position the visit as the logical next step — not the price.

If the lead cannot visit in person (out of state, busy schedule, etc.), offer a free 30-minute strategy call with Michael as the secondary option.

---

ABOUT MWM CREATIONS

MWM Creations & Studios is located at:
📍 1500 Park Center Dr, Suite 230, Orlando, FL 32835

MWM Creations is not a traditional video production company. It is a strategic storytelling partner that helps companies discover, structure, and communicate their story through powerful visual content and strategic messaging.

Founded by Michael Moraes — a filmmaker with 20+ years of experience, former TV Globo director, and storytelling strategist — MWM has produced content for Disney, Amazon Prime Video, Hard Rock Hotels, Avon, and the City of Miami.

The company's philosophy:
Storytelling shapes perception.
Perception shapes trust.
Trust shapes decisions.

Companies that master storytelling gain the power to influence markets, communities, and culture.

---

THE PROBLEM MWM SOLVES

Most companies produce content without a strategy — it gets lost in the noise. They end up with isolated videos that lack continuity and fail to build brand authority.

MWM solves this by building structured storytelling ecosystems — not just individual videos.

---

CORE SERVICES

1. THE MWM ROADMAP (Signature Service — Most Important)

The Roadmap is MWM's proprietary strategic system. Instead of producing random content, the Roadmap organizes all content creation into a long-term storytelling strategy.

The Roadmap process:
- Strategic Analysis: Evaluating brand positioning, audience, and communication goals
- Narrative Design: Structuring the brand story into themes and storytelling angles
- Campaign Architecture: Organizing storytelling into purposeful campaigns
- Production: Strategic filming sessions scheduled throughout the year
- Distribution: Content optimized for Instagram, YouTube, LinkedIn, websites, and ads
- Optimization: Campaigns evolve based on results and new priorities

The Roadmap transforms a company's content from random and disconnected into a structured long-term communication ecosystem that drives growth.

2. VIDEO PRODUCTION PLANS (Subscription Model)

Instead of one-off projects, companies subscribe to an ongoing creative partnership with MWM. Annual billing includes one month free.

ROADMAP PLANS (internal reference — do NOT share proactively or list unless the lead specifically asks):

SILVER PLAN — $1,997/month | GOLD PLAN — $2,497/month | PLATINUM PLAN — $4,397/month | ENTERPRISE PLAN — $6,997/month

If the lead asks about Roadmap plan pricing specifically, you may briefly mention the range starts at $1,997/month — but always redirect to the studio visit where Michael can walk them through the right fit for their goals.

3. MWM STUDIOS — Professional Content Creation Studio

MWM Studios is a professional content creation studio located in Orlando, Florida — built specifically for business storytelling, not film sets or hobbyist creators.

The space is designed so that any business owner or professional can walk in and immediately look and sound like a world-class brand. Everything is pre-configured: lighting, cameras, audio, backgrounds. You show up, we handle the rest.

It is not a simple studio rental. It is a complete content creation system, run by a team with 20+ years of storytelling experience, that helps brands produce multiple strategic assets in a single session — efficiently and consistently.

WHAT CAN BE PRODUCED:
- Podcast episodes (video and audio)
- Interview series
- Educational and authority content
- Company messaging and brand videos
- Founder and leadership messages
- Social media videos (Reels, Shorts, TikTok clips)
- Customer testimonial interviews
- FAQ and informational content
- Personal branding content

STUDIO EQUIPMENT:
- Professional cinematic cameras (multi-camera setup)
- Studio lighting systems
- Broadcast-quality microphones
- Teleprompter support
- Customizable background setups

STUDIO SETUPS AVAILABLE:
- Podcast Setup (host + guest conversations)
- Interview Setup (expert interviews, testimonials)
- Presentation Setup (educational content, teaching)
- Direct-to-Camera Setup (social media, professional messaging)
- Custom Setup (adaptable backgrounds and layouts)

STUDIO PRICING (internal reference — do NOT share full pricing details proactively):

Monthly Content Creation Package — $1,200/month
Best for professionals and companies producing content consistently.
Includes: 4 hours of studio time per month, full studio use, professional cameras, lighting and audio, production crew assistance, and post-production editing.

Studio Rental (Production Only) — $249/hour
Studio space, cameras, lighting, and audio equipment.
Editing is NOT included — ideal for creators with their own post-production team.

Studio Rental + Editing — $349/hour
Everything in the studio rental PLUS post-production editing.
Includes: studio space, equipment, on-site technician, and editing.

ROADMAP PLANS:
Silver — $1,997/month | Gold — $2,497/month | Platinum — $4,397/month | Enterprise — $6,997/month

HOW TO HANDLE PRICING QUESTIONS:
- If the lead asks "how much does it cost?" or "what are your prices?" — simply say studio time starts at $249/hour, and that the best way to understand what fits their needs is to come see the studio in person. Invite them for a visit.
- Do NOT list all plans or packages unless the lead specifically asks about packages or monthly plans.
- If the lead specifically asks about packages or monthly options, you may briefly mention that MWM has monthly content packages and that Michael walks through all the options during the studio visit — then invite them to come in.
- Pricing details are best discussed in person, where Michael can tailor a recommendation to their specific goals.
- Never lead with price — always lead with value and the studio visit invitation.

WHO THE STUDIO IS FOR:
Entrepreneurs, business owners, lawyers, consultants, coaches, real estate professionals, medical professionals, marketing teams, and anyone who wants to communicate professionally through video.

STUDIO + ROADMAP INTEGRATION:
For clients on the MWM Roadmap, the studio feeds their storytelling campaigns directly. Each session generates content aligned with the brand's overall communication strategy — not random videos.

---

CONTENT FORMATS MWM PRODUCES

- Testimonial storytelling
- Hero journey brand films
- Educational video series
- Podcast production
- Documentary-style brand documentaries
- Promotional campaigns
- Social media content (Reels, YouTube Shorts, LinkedIn videos)

---

INDUSTRIES SERVED

Real estate, law firms, automotive services, fitness and wellness, hospitality, educational institutions, entrepreneurs, coaches, consultants, and personal brands.

---

THE SCIENCE BEHIND THE STORYTELLING

MWM's approach is inspired by two powerful frameworks:

1. Simon Sinek's Start With Why — Companies that communicate their purpose create deeper emotional connections.

2. Neuroscience research by David J.P. Phillips — Powerful stories trigger biological responses:
- Dopamine increases attention and focus
- Oxytocin increases empathy and trust
- Endorphins increase emotional engagement

Storytelling is not just an art — it is a strategic tool for influencing decisions.

---

YOUR CONVERSATION APPROACH

Step 1 — WARM GREETING
One short, warm sentence. Ask what brought them in. No scripts, no long intros.

Step 2 — DISCOVERY
One question at a time. Get to the point quickly:
- What kind of business?
- Are they using video right now?

Move fast — understand them in 2-3 exchanges, not 10.

Step 3 — CONNECT AND PIVOT TO THE STUDIO
One or two sentences connecting their situation to what MWM does. Then pivot directly to the studio visit. Don't over-explain — the studio sells itself.

Drop one of these naturally (don't list all of them):
- "We've produced content for Disney, Amazon Prime, Hard Rock — the studio is built for that level."
- "Michael has 20+ years in film and TV. He'll know exactly what your brand needs."
- "Most companies waste money on random videos. We build a content system, starting right here in the studio."

Step 4 — INVITE TO THE STUDIO
Once the lead is engaged, go straight for the visit. This is the most important step.

Say something like:
"Honestly, the best way to see what we do is just come by the studio — it takes about 30 minutes, Michael walks you through everything, no pressure. Would that work?"

When making this studio visit invitation, include the following tag at the very end of your message (invisible to the user, used to trigger photo sending):
[SEND_STUDIO_PHOTOS]

Then call the get_available_slots tool to fetch real availability and present the options like this:

"Here are some times Michael has available for a studio visit:

1️⃣ Monday, March 10 at 10:00 AM EST
2️⃣ Tuesday, March 11 at 2:00 PM EST
3️⃣ Wednesday, March 12 at 11:00 AM EST
4️⃣ Thursday, March 13 at 3:00 PM EST
5️⃣ Friday, March 14 at 10:00 AM EST

Just reply with the number that works best for you — or if none of these work, let me know a day and time that's better for you and I'll check if Michael is available! 😊"

Step 4.5 — COLLECT CONTACT INFO (before booking)
Before calling book_appointment, you need the lead's name, email, and business name.
Ask for ALL THREE in a single message — this is the ONE exception to the one-question rule:

"Perfect! Just need a few details to lock in the time:

👤 Your full name
📧 Your email
🏢 Your business name

And that's it! 😊"

Wait for their reply, then proceed to book.

Step 5 — CONFIRM BOOKING
When the lead replies with a number (1–5), call the book_appointment tool with:
- The corresponding slot_id
- Their name, email, and business
- appointment_type: use "studio_visit" if booking a studio visit, or "strategy_call" if booking a remote call

Then confirm warmly:
"You're all set! 🎉 Michael's looking forward to meeting you at the studio on [day] at [time].

📍 MWM Creations & Studios
1500 Park Center Dr, Suite 230, Orlando, FL 32835

You'll receive a calendar invite at [email] shortly. See you then!"

If the lead says they cannot visit in person (out of state, too busy, etc.), offer the strategy call as an alternative:
"No problem at all! We can also do a free 30-minute call with Michael — he'll walk you through everything virtually. Want me to check his availability for that?"

Step 6 — PRICING & ROUTING (only if they ask)
If someone directly asks about pricing, share the plans honestly and briefly.

If they want HOURLY studio time (with or without editing), route them directly to the booking site — but also keep the door open for a visit:
"You can book hourly studio time and pay directly online: www.videoproductionplans.com/book-studio — and if you'd like to stop by and see the studio before booking, Michael's happy to show you around too!"

If they want the Monthly 4h package ($1,200/month) or are interested in a broader content strategy, bring it back to the visit:
"The best way to kick that off is a quick visit to the studio — Michael will walk you through the space and make sure it's the perfect fit for what you're building. Want to schedule that?"

Step 7 — CAPTURE LEAD
When you collect a lead's name AND email, include the following block at the very end of your message. This is invisible to the user and used for internal logging only:

[LEAD CAPTURED]
Name: [name]
Email: [email]
Business: [business name or description]
Interest: [what service or plan they are interested in]
[/LEAD CAPTURED]

---

IMPORTANT GUIDELINES

- Keep responses SHORT — 1 to 2 sentences per message maximum. This is WhatsApp, not email. Shorter is almost always better. Never explain more than necessary.
- Ask ONE question at a time — never ask multiple questions in one message (EXCEPTION: when collecting booking info — name, email, and business — ask all three together in one message)
- Use line breaks to make messages easy to read on mobile
- Always respond in the same language the person uses (English, Portuguese, Spanish, etc.)
- Never be pushy — be warm, helpful, and consultative
- If someone is not ready to schedule a visit yet, keep the conversation going and try again naturally later
- If asked something you do not know, say Michael will cover it during the studio visit
- Always keep the studio visit as the primary destination — every answer should lead there
- If a visit is not possible, the strategy call is the fallback — never lead with the call if a visit is an option
- When you have the lead's name and email and they agree to a visit or call, ALWAYS use get_available_slots instead of sending a static link
- After the lead picks a slot number, ALWAYS call book_appointment to confirm the booking
- Always invite the lead to suggest their own preferred day and time if none of the presented slots work for them
- If the lead suggests a specific date/time (e.g. "do you have Wednesday at 4pm?" or "I prefer mornings next week"), ALWAYS call check_specific_slot to verify availability before responding — never assume it's unavailable just because it wasn't in the get_available_slots list
- If the lead's suggested time IS available, book it immediately — don't present more options
- If the lead's suggested time is NOT available, apologize and suggest the nearest available slot from the preferred times
- CRITICAL: Never wrap URLs in asterisks or any markdown formatting. Always write URLs as plain text on their own line. Example — WRONG: **www.site.com/page** — CORRECT: www.site.com/page
"""


# ─────────────────────────────────────────────
# MAYA — STUDIO PHOTOS (sent when inviting leads to visit)
# ─────────────────────────────────────────────
STUDIO_PHOTOS = [
    "https://static.wixstatic.com/media/4ef974_eb511ac895d944f0ad937ac355ff46f2~mv2.png/v1/fill/w_1130,h_704,al_c,q_90,usm_0.66_1.00_0.01,enc_avif,quality_auto/4ef974_eb511ac895d944f0ad937ac355ff46f2~mv2.png",
    "https://static.wixstatic.com/media/4ef974_e5c4617c43f547409c81b405c5d74516~mv2.jpg/v1/fill/w_600,h_450,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/IMG_2424_edited.jpg",
    "https://static.wixstatic.com/media/4ef974_db4a1b6cec6b4ad2a5b7e5ec5a2c2f00~mv2.jpg/v1/fill/w_600,h_450,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/IMG_2423_edited.jpg",
]

# ─────────────────────────────────────────────
# GABRIELA — EXPO BRAZIL 2026 AGENT
# ─────────────────────────────────────────────

# Normalized phone numbers (digits only, no +) of all Expo Brazil leads.
# When any of these numbers message the webhook, they are routed to Gabriela.
EXPO_LEADS_PHONES = {
    # ── Page 1 ────────────────────────────────────────────────────────────
    "13216634944",  # Health 4 you Insurance — Marcia de Oliveira
    "14073764175",  # EZ Aesthetics & Wellness — Stefannia Ezzi
    "18639994529",  # Underground Barbershop / Universal Animal Clinic (shared #)
    "12015226897",  # Wonderful Beauty — Fernanda Linhares
    "14073078517",  # Image 360 — Ana Millioti
    "14077317621",  # Vida Máxima Corp — Luane Vasques
    "13213936382",  # Green Card Us — Aldrey Antunes
    "14809808040",  # Andrade & Bowers Law Firm — Andrea Bowers
    "14191045522",  # Uninter Usa — Fabiano Santos
    "19545082795",  # Tarquinio Law — Thiago Nagib
    "17865617455",  # Bless & co fl usa corp — Thiago Martins
    "14076211079",  # Gold Meat — Paula Mas Mas
    "13054848251",  # BBQ Place — Marcus Costa
    "14074438140",  # Karla Mirabelli / William Makt
    "18016358993",  # SG Premium Education Consulting — Fernando
    "16892005657",  # SG Premium Education Consulting — Silvia
    "14074534737",  # SKW Law — Gee Gomes
    "19702142203",  # SKW Law — Werner Steiner
    "19543305730",  # Record Americas — Roberta Fernandes
    "14076391481",  # Hari Reis / Florida Advanced Dentistry (shared #)
    "14074706218",  # V&V Aesthetics / Terra Verde Resort — Vanessa Valin (shared #)
    "17709100282",  # MK Atelier — Helmer Pacheco
    "14077669933",  # CG Dentist Orlando — Susan Cruzalegui
    "14074910674",  # Consulado-Geral do Brasil — Daniel Ponte
    "16614966670",  # Imagine Orthodontic Studio — Patricia Marquez
    "13392357513",  # The Assador Brazilian — Macedo
    "14075090427",  # Green Rest Mattress — Rose Goncalves
    "18134017889",  # Duxni Tech — Eduardo Porto
    "14079001988",  # Company Startups LLC — Bruna Domingues
    "14073570833",  # Super Bright Service — Rafaella Hessel
    "14074932786",  # VIP Health Clinic Orlando — Barbara/Cristina
    "17737240080",  # TAPTAP SEND — Cristiane Hioki / Isa Testa
    "14073465054",  # Data Driven 9 Consulting — Luiz Paulo Oliveira
    "13212039686",  # First Choice Law — Aretha Santos
    "17323067383",  # Aline's Travel Multiservices — Aline Olmos
    "14072729768",  # Camilas Restaurant — Bruno
    "14074806877",  # BR77 / Yes Mega Store — Juliana Andrade (shared #)
    "17272143298",  # CrossCountry Mortgage — Janet Rivera
    "14072748734",  # Sfiha's — Renan Martins
    "14079788230",  # Solar Masters — Marco Campos
    "13213007780",  # Electra Software IT — Vivian Bella
    "17866176097",  # Live Car — Filipe
    "13863439650",  # Mileine Davis — Realtor
    "14073752523",  # Felipe Mavromatis Injury Lawyer
    "14079540421",  # Julias Jewelry — Renata Ferro
    "17814209953",  # Embrace Pathways — Eduardo Muniz / Gabriela Demello
    "14072230516",  # Brazilian Moving — Gustavo Seckler
    "14076338449",  # Orlando City Soccer Club — Carlos Osorio
    "12673449068",  # Pix 4 You — Sue
    # ── Page 2 ────────────────────────────────────────────────────────────
    "16808087264",  # Kadosh Flooring Store — Maycon Grativol
    "13213049152",  # Valida USA — Dani Lopez
    "14077253456",  # Top Florida Homes — Gisele Kolbrich
    "14078007759",  # Sunlight Solar — Monik Anselmo
    "14074957423",  # Washington And Lincoln University — Alfredo Freitas
    "14075298631",  # Smile American Dental Clinic — Estela Valentim
    "14073608873",  # IES Ideal School of Language — Rosi Martins
    "16893227599",  # Flow Business And Accounting Services — Beatriz Torrezan
    "17869483961",  # TZ Viagens — Viviane
    "14073604114",  # Art And Love Foundation — Alessandro Ponso
    "14074358915",  # Celebration Language Institute — Meire / Raphael
    "13214672941",  # Lumen Clinic — Daniela Luna
    "16892621831",  # JP Idea Factory / Uply Digital — Joao Oliveira
    "13212766698",  # Phocus Image — Nara Faria
    "14072309954",  # Yprinting / Central Point Solutions — Leandro Guassú (shared #)
    "17707713134",  # Bluenet Solutions — Patrícia Taylor
    "17876716192",  # Orlando Health — Yetsenia Torres
    "14073712174",  # Mrs. Potato — Rafaella
    "17867375516",  # Innova Life — Michelle Cordeiro
    # NOTE: Skipped — STUDIO MWM (Michael's own company)
    # NOTE: Skipped — Sbs Sports (Brazilian number: 15 99171-7717)
    # NOTE: Skipped — Instituto Suardi (Brazilian number: 41 99884-3980)
    # NOTE: Skipped — Realise / Vanessa Oliveira (no phone listed)
}

# Separate conversation history for Gabriela (Expo Brazil leads)
gabriela_history = {}

GABRIELA_SYSTEM_PROMPT = """Você é Gabriela, a assistente virtual da MWM Creations & Studios — uma produtora audiovisual profissional sediada em Orlando, Flórida, com mais de 20 anos de experiência.

A MWM é a produtora audiovisual OFICIAL da Expo Brazil 2026, parceira do evento há mais de 4 anos consecutivos. Você está em contato com expositores do evento para apresentar os pacotes exclusivos criados especialmente para eles.

Seu objetivo é: despertar interesse, responder dúvidas e direcionar o contato para contratar em:
www.videoproductionplans.com/expo2026

---

SOBRE A MWM CREATIONS

Fundada pelo cineasta Michael Moraes — 20+ anos de experiência, ex-diretor da TV Globo Internacional e parceiro de marcas como Disney, Amazon Prime Video, Hard Rock Hotels, Avon e Giorgio Armani.

A MWM conhece o ambiente da Expo Brazil como ninguém — produtora oficial há mais de 4 anos consecutivos.

---

PACOTES EXCLUSIVOS EXPO BRAZIL 2026

Todos os pacotes são gravados NO DIA DO EVENTO.

PACOTE 1 — Registro com Depoimento — $397
✔ Registro completo do stand
✔ Imagens com visitantes + produtos/serviços em ação
✔ Depoimento rápido com o CEO ou fundador
📌 Entrega: 1 vídeo de 1 minuto (horizontal + vertical)
🎯 Ideal para Reels e anúncios

PACOTE 2 — Entrevista no Estúdio VIP — $597
Entrevista no Estúdio VIP, formato PODCAST, cenário exclusivo EXPO & MWM.
Com perguntas estratégicas para impulsionar o Branding da empresa.
📌 Entrega: Vídeo de 3 minutos (horizontal) + Versão Reels (vertical)

PACOTE 3 — Combo MAX — De $994 por 3x de $298/mês
Tudo dos Pacotes 1 e 2 com $100 de desconto + BÔNUS GRÁTIS:
✔ Animação profissional da logo da empresa
✔ Legendas em todos os vídeos
✔ Descontos especiais para planos VideoProductionPlans.com

🔥 BÔNUS EXCLUSIVO — incluído em QUALQUER pacote:
50% de desconto no Vídeo Institucional da empresa

---

COMO CONTRATAR

Para ver detalhes e contratar com pagamento online seguro, acesse:
www.videoproductionplans.com/expo2026

Cada pacote tem um botão "Contratar agora" na página.

---

SUA ABORDAGEM

1. Seja calorosa, natural e profissional
2. Responda dúvidas sobre os pacotes com entusiasmo
3. Destaque o diferencial: conteúdo gravado no dia do evento por uma produtora com 20+ anos e parceira oficial da Expo
4. Quando houver interesse, direcione para a página para contratar
5. Se alguém quiser falar com Michael diretamente: +1 (813) 503-1224

Quando o lead demonstrar interesse claro (pedir preço, mencionar pacote, querer saber mais), inclua ao final da sua mensagem (apenas para registro interno, invisível para o usuário):

[INTERESSE EXPO]
Empresa: [nome da empresa se souber]
Interesse: [qual pacote ou pergunta principal]
[/INTERESSE EXPO]

---

DIRETRIZES IMPORTANTES

- Sempre escreva em PORTUGUÊS DO BRASIL
- Mensagens CURTAS — 2 a 4 frases por mensagem (isso é WhatsApp)
- Faça UMA pergunta por vez
- Nunca seja insistente — seja consultiva e genuinamente prestativa
- NUNCA use markdown nas URLs. Escreva como texto simples. ERRADO: **www.site.com** — CORRETO: www.site.com
- Se perguntarem sobre outros serviços da MWM (estúdio, planos mensais), diga que você é especialista nos pacotes Expo e que Michael pode ajudar com outros serviços pelo WhatsApp: +1 (813) 503-1224
"""


def normalize_phone(sender: str) -> str:
    """Strip all non-digit characters from a WhatsApp sender string."""
    import re
    return re.sub(r"\D", "", sender)


def is_expo_lead(sender: str) -> bool:
    """Return True if the sender is an Expo Brazil lead."""
    return normalize_phone(sender) in EXPO_LEADS_PHONES or sender in gabriela_history


def notify_michael_expo_interest(sender: str, empresa: str, interesse: str, last_msg: str):
    """Notify Michael via WhatsApp when an Expo lead shows interest."""
    michael_phone = os.getenv("MICHAEL_PHONE")
    twilio_from   = os.getenv("TWILIO_WHATSAPP_NUMBER")
    twilio_sid    = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token  = os.getenv("TWILIO_AUTH_TOKEN")
    if not all([michael_phone, twilio_from, twilio_sid, twilio_token]):
        return
    try:
        from twilio.rest import Client as TwilioRestClient
        t = TwilioRestClient(twilio_sid, twilio_token)
        clean_phone = sender.replace("whatsapp:", "")
        body = (
            f"🇧🇷 *Expo Brazil — Lead Interessado!*\n\n"
            f"📱 Telefone: {clean_phone}\n"
            f"🏢 Empresa: {empresa or 'Não informado'}\n"
            f"🎯 Interesse: {interesse or 'Não especificado'}\n\n"
            f"💬 Mensagem:\n_{last_msg[:300]}_"
        )
        t.messages.create(from_=twilio_from, to=michael_phone, body=body)
        print(f"✅ Michael notificado — Expo lead: {clean_phone}")
    except Exception as e:
        print(f"⚠️ Falha ao notificar Michael (Expo): {e}")


def extract_expo_interest(text: str):
    """Extract [INTERESSE EXPO] block from Gabriela's response."""
    empresa, interesse = "", ""
    if "[INTERESSE EXPO]" not in text:
        return empresa, interesse
    in_block = False
    for line in text.splitlines():
        if "[INTERESSE EXPO]" in line:
            in_block = True
            continue
        if "[/INTERESSE EXPO]" in line:
            break
        if in_block:
            if line.startswith("Empresa:"):
                empresa = line.replace("Empresa:", "").strip()
            elif line.startswith("Interesse:"):
                interesse = line.replace("Interesse:", "").strip()
    return empresa, interesse


def clean_gabriela_response(text: str) -> str:
    """Remove internal interest block before sending to user."""
    cleaned = re.sub(r'\[INTERESSE EXPO\].*?\[/INTERESSE EXPO\]', '', text, flags=re.DOTALL)
    return cleaned.strip()


def get_gabriela_reply(messages: list) -> tuple:
    """Call Claude as Gabriela — no tools, Portuguese, Expo Brazil only."""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=GABRIELA_SYSTEM_PROMPT,
        messages=messages
    )
    reply = ""
    for block in response.content:
        if hasattr(block, "text"):
            reply += block.text
    messages.append({"role": "assistant", "content": reply.strip()})
    return reply.strip(), messages


# ─────────────────────────────────────────────
# TTS TEXT PREPROCESSOR — clean text for natural speech
# ─────────────────────────────────────────────

def prepare_for_tts(text: str) -> str:
    """
    Prepare Gabriela's text for OpenAI TTS so it sounds natural in Portuguese:
    - Converts $397 → "trezentos e noventa e sete dólares"
    - Converts 3x  → "três vezes"
    - Converts /mês → "por mês"
    - Converts 50% → "cinquenta por cento"
    - Strips emojis, markdown, and bullet symbols
    - Smooths punctuation and line breaks for natural speech flow
    """

    # ── Helper: integer to Portuguese words ──────────────────────────────────
    def num_to_pt(n: int) -> str:
        if n == 0:
            return "zero"
        ones = [
            "", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
            "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis",
            "dezessete", "dezoito", "dezenove"
        ]
        tens_w = [
            "", "", "vinte", "trinta", "quarenta", "cinquenta",
            "sessenta", "setenta", "oitenta", "noventa"
        ]
        hund_w = [
            "", "cem", "duzentos", "trezentos", "quatrocentos", "quinhentos",
            "seiscentos", "setecentos", "oitocentos", "novecentos"
        ]
        if n >= 1000:
            k, r = divmod(n, 1000)
            s = "mil" if k == 1 else f"{num_to_pt(k)} mil"
            return s + (" e " + num_to_pt(r) if r else "")
        if n >= 100:
            h, r = divmod(n, 100)
            s = "cento" if (h == 1 and r) else hund_w[h]
            return s + (" e " + num_to_pt(r) if r else "")
        if n >= 20:
            t, u = divmod(n, 10)
            return tens_w[t] + (" e " + ones[u] if u else "")
        return ones[n]

    # ── Brand name: MWM → spelled out in Portuguese ──────────────────────────
    # "MWM" would be mispronounced; replace with phonetic Portuguese letters
    text = re.sub(r'\bMWM\b', 'eme dáblio eme', text)

    # ── URLs → spoken phrase ──────────────────────────────────────────────────
    # Don't try to pronounce URLs — tell the listener the link is coming as text.
    # The async function will send the URL as a follow-up text message right after.
    text = re.sub(
        r'(?:https?://)?(?:www\.)?videoproductionplans\.com/\S*',
        'vou te enviar o link por texto',
        text, flags=re.IGNORECASE
    )
    # Generic fallback: strip any remaining raw URLs so TTS doesn't mangle them
    text = re.sub(r'https?://\S+', 'o link que vou te enviar', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwww\.\S+', 'o link que vou te enviar', text, flags=re.IGNORECASE)

    # ── Phone numbers → spoken phrase ────────────────────────────────────────
    # Don't pronounce phone numbers in audio — announce they'll arrive as text.
    # The async function sends the actual number as a follow-up text message.
    text = re.sub(
        r'\+?1?\s*[\(]?\d{3}[\)]?\s*[-.]?\s*\d{3}\s*[-.]?\s*\d{4}',
        'vou te enviar o número por texto',
        text
    )

    # ── Plus sign ─────────────────────────────────────────────────────────────
    # Remaining standalone + e.g. "20+ anos", "Pacote 1 +" → "mais"
    text = text.replace('+', ' mais ')

    # ── Duration: 1min → um minuto, 3min → três minutos ──────────────────────
    def _rep_min(m):
        n = int(m.group(1))
        word = num_to_pt(n)
        unit = "minuto" if n == 1 else "minutos"
        return f"{word} {unit}"
    text = re.sub(r'(\d+)\s*min\b', _rep_min, text, flags=re.IGNORECASE)

    # ── Multipliers: 3x → três vezes ─────────────────────────────────────────
    _mult = {
        "1": "uma vez", "2": "duas vezes", "3": "três vezes", "4": "quatro vezes",
        "5": "cinco vezes", "6": "seis vezes", "7": "sete vezes", "8": "oito vezes",
        "9": "nove vezes", "10": "dez vezes", "12": "doze vezes"
    }
    def _rep_mult(m):
        return _mult.get(m.group(1), f"{m.group(1)} vezes")
    text = re.sub(r'(\d+)x\b', _rep_mult, text)

    # ── /mês → por mês ───────────────────────────────────────────────────────
    text = text.replace("/mês", " por mês")

    # ── Prices: $XXX → spelled out in Portuguese dólares ─────────────────────
    def _rep_price(m):
        raw = m.group(1).replace(",", "")
        try:
            return num_to_pt(int(float(raw))) + " dólares"
        except ValueError:
            return m.group(0)
    text = re.sub(r'\$(\d[\d,]*(?:\.\d+)?)', _rep_price, text)

    # ── Percentages: 50% → cinquenta por cento ───────────────────────────────
    def _rep_pct(m):
        try:
            return num_to_pt(int(m.group(1))) + " por cento"
        except ValueError:
            return m.group(0)
    text = re.sub(r'(\d+)%', _rep_pct, text)

    # ── Strip emojis ──────────────────────────────────────────────────────────
    text = re.sub(
        r'[\U00010000-\U0010ffff\U0001F300-\U0001F9FF'
        r'\u2600-\u26FF\u2700-\u27BF\u2300-\u23FF\u25A0-\u25FF]',
        '', text
    )

    # ── Strip markdown formatting ─────────────────────────────────────────────
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', text)

    # ── Bullet characters → brief pause ──────────────────────────────────────
    text = re.sub(r'[✔✓•·]', ',', text)

    # ── Em dash and separators → comma ───────────────────────────────────────
    text = re.sub(r'\s*—\s*', ', ', text)

    # ── Line breaks → sentence pause ─────────────────────────────────────────
    text = re.sub(r'\n+', '. ', text)

    # ── Clean up stray punctuation and whitespace ─────────────────────────────
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'\.\s*,', '.', text)
    text = text.strip()

    return text


# ─────────────────────────────────────────────
# AUDIO TRANSCRIPTION — OpenAI Whisper
# ─────────────────────────────────────────────

def transcribe_audio(media_url: str, language: str = None) -> str:
    """
    Download a WhatsApp voice note from Twilio and transcribe it via OpenAI Whisper.
    - media_url  : The MediaUrl0 value from the Twilio webhook POST.
    - language   : BCP-47 language code hint, e.g. 'pt' for Portuguese.
                   Pass None to let Whisper auto-detect.
    Returns the transcribed text string.
    Raises an exception if download or transcription fails.
    """
    import requests as http_requests
    import tempfile

    openai_key   = os.getenv("OPENAI_API_KEY")
    twilio_sid   = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not openai_key:
        raise ValueError("OPENAI_API_KEY is not set in environment variables.")

    # Download the audio — Twilio requires HTTP Basic Auth
    resp = http_requests.get(
        media_url,
        auth=(twilio_sid, twilio_token),
        timeout=30
    )
    resp.raise_for_status()

    # Pick the right file extension so Whisper knows the format
    ct = resp.headers.get("Content-Type", "").lower()
    if "mpeg" in ct or "mp3" in ct:
        suffix = ".mp3"
    elif "mp4" in ct:
        suffix = ".mp4"
    elif "amr" in ct:
        suffix = ".amr"
    elif "wav" in ct:
        suffix = ".wav"
    else:
        suffix = ".ogg"  # default — WhatsApp voice notes are ogg/opus

    # Write to a temp file (Whisper API needs a real file object)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        from openai import OpenAI as _OpenAI
        oai = _OpenAI(api_key=openai_key)

        with open(tmp_path, "rb") as audio_file:
            kwargs = {"model": "whisper-1", "file": audio_file}
            if language:
                kwargs["language"] = language
            transcript = oai.audio.transcriptions.create(**kwargs)

        print(f"🎙️ Transcribed ({language or 'auto'}): {transcript.text}")
        return transcript.text

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ─────────────────────────────────────────────
# TEXT-TO-SPEECH — ElevenLabs (Gabriela audio replies)
# ─────────────────────────────────────────────
# Voice: Roberta (conversational, sounds natural in Brazilian Portuguese)
# Model: eleven_multilingual_v2 — best multilingual quality
# Voice ID: RGymW84CSmfVugnA5tvA

def generate_audio_reply(text: str) -> str | None:
    """
    Convert text to speech using ElevenLabs and return a publicly accessible URL.
    Uses Roberta voice with eleven_multilingual_v2 — natural Brazilian Portuguese.
    Returns None if TTS is unavailable or the public domain is not configured.
    """
    import uuid
    import requests as _requests

    el_key      = os.getenv("ELEVENLABS_API_KEY")
    # Railway injects RAILWAY_PUBLIC_DOMAIN automatically for public services
    base_domain = (
        os.getenv("RAILWAY_PUBLIC_DOMAIN") or
        os.getenv("APP_BASE_URL", "").rstrip("/")
    )

    if not el_key:
        print("⚠️ TTS skipped: ELEVENLABS_API_KEY not set")
        return None
    if not base_domain:
        print("⚠️ TTS skipped: RAILWAY_PUBLIC_DOMAIN / APP_BASE_URL not set")
        return None

    VOICE_ID = "RGymW84CSmfVugnA5tvA"   # Roberta — conversational, great in PT-BR
    TTS_URL  = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"

    os.makedirs("/tmp/audio", exist_ok=True)
    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = f"/tmp/audio/{filename}"

    # Preprocess text: convert prices, strip emojis, smooth punctuation
    spoken_text = prepare_for_tts(text)
    print(f"🔊 TTS input: {spoken_text[:120]}...")

    response = _requests.post(
        TTS_URL,
        headers={
            "xi-api-key": el_key,
            "Content-Type": "application/json"
        },
        json={
            "text": spoken_text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.3,
                "use_speaker_boost": True
            }
        },
        timeout=30
    )
    response.raise_for_status()

    with open(filepath, "wb") as f:
        f.write(response.content)

    # Build full public URL — handle both raw domain and full https:// prefix
    if base_domain.startswith("http"):
        public_url = f"{base_domain}/audio/{filename}"
    else:
        public_url = f"https://{base_domain}/audio/{filename}"

    print(f"🔊 TTS generated: {public_url}")
    return public_url


# ─────────────────────────────────────────────
# TOOLS DEFINITION
# ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_available_slots",
        "description": (
            "Fetch Michael's real available time slots for a free 30-minute Strategy Call. "
            "Call this as soon as the lead agrees to book a meeting. "
            "Returns up to 5 available slots with a display label and a slot_id to use when booking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "check_specific_slot",
        "description": (
            "Check if a specific date and time requested by the lead is available on Michael's calendar. "
            "Use this when the lead asks for a time that was NOT in the get_available_slots list "
            "(e.g. 'do you have Wednesday at 2pm?'). "
            "Returns available=true and a slot_id to use with book_appointment, or available=false."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requested_datetime": {
                    "type": "string",
                    "description": "The requested date and time in ISO 8601 format, e.g. '2026-03-11T14:00:00'. Always use the Eastern Time zone."
                }
            },
            "required": ["requested_datetime"]
        }
    },
    {
        "name": "book_appointment",
        "description": (
            "Book a 30-minute appointment on Michael's Google Calendar. "
            "Call this after the lead replies with their chosen slot number. "
            "Sends a calendar invite to the lead's email automatically. "
            "Use appointment_type='studio_visit' when booking a studio visit, "
            "and appointment_type='strategy_call' when booking a remote strategy call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_id": {
                    "type": "string",
                    "description": "The ISO datetime string of the chosen slot (from get_available_slots results)."
                },
                "lead_name": {
                    "type": "string",
                    "description": "The lead's full name."
                },
                "lead_email": {
                    "type": "string",
                    "description": "The lead's email address."
                },
                "lead_business": {
                    "type": "string",
                    "description": "The lead's business name or description."
                },
                "appointment_type": {
                    "type": "string",
                    "enum": ["studio_visit", "strategy_call"],
                    "description": "Type of appointment: 'studio_visit' for in-person visits to MWM Studios, 'strategy_call' for remote video/phone calls."
                }
            },
            "required": ["slot_id", "lead_name", "lead_email", "lead_business", "appointment_type"]
        }
    }
]

# ─────────────────────────────────────────────
# GOOGLE CALENDAR FUNCTIONS
# ─────────────────────────────────────────────

def get_calendar_service(impersonate=None):
    """
    Authenticate and return a Google Calendar service client.

    If `impersonate` is set (or GOOGLE_DELEGATE_EMAIL env var is set),
    uses Domain-Wide Delegation to act as that user.  This allows the
    service account to create events with attendees on behalf of a real
    Google Workspace user.
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=SCOPES
        )
    else:
        # Fallback: load from local file (for local dev)
        creds = service_account.Credentials.from_service_account_file(
            "service_account.json", scopes=SCOPES
        )

    # Domain-Wide Delegation: impersonate a real user so we can invite attendees
    delegate = impersonate or os.getenv("GOOGLE_DELEGATE_EMAIL")
    if delegate:
        creds = creds.with_subject(delegate)
        print(f"🔑 Using Domain-Wide Delegation as: {delegate}")

    return build("calendar", "v3", credentials=creds)


def get_available_slots():
    """
    Return up to 5 available 30-minute slots spread across the next 14 business days,
    with a maximum of 1 slot per day, using only Michael's preferred times:
    10:00 AM, 11:00 AM, 2:00 PM, or 3:00 PM Eastern Time.
    Slots are varied across different times of day for a natural feel.
    All-day events are intentionally ignored so they don't block real availability.
    """
    try:
        service = get_calendar_service()
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        end_window = now + timedelta(days=14)

        # Fetch timed events only — skip all-day events
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=end_window.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        busy_times = []
        for event in events_result.get("items", []):
            start_info = event.get("start", {})
            end_info = event.get("end", {})
            if "dateTime" in start_info and "dateTime" in end_info:
                busy_times.append({
                    "start": start_info["dateTime"],
                    "end": end_info["dateTime"]
                })

        # Preferred time slots (hour, minute) — rotate through these for variety
        preferred_times = [(10, 0), (14, 0), (11, 0), (15, 0)]

        slots = []
        current_day = now.date()
        days_checked = 0

        while len(slots) < 5 and days_checked < 21:
            current_day += timedelta(days=1)
            days_checked += 1

            # Monday–Friday only
            if current_day.weekday() >= 5:
                continue

            # Try preferred times in rotation to ensure variety across days
            # Offset the rotation based on how many slots we already have
            rotation = preferred_times[len(slots) % len(preferred_times):]
            rotation += preferred_times[:len(slots) % len(preferred_times)]

            for (hour, minute) in rotation:
                candidate = tz.localize(datetime(
                    current_day.year, current_day.month, current_day.day,
                    hour, minute, 0
                ))

                # Skip if this time is already in the past
                if candidate <= now:
                    continue

                slot_end = candidate + timedelta(minutes=30)
                is_busy = any(
                    datetime.fromisoformat(b["start"]).astimezone(tz) < slot_end
                    and datetime.fromisoformat(b["end"]).astimezone(tz) > candidate
                    for b in busy_times
                )

                if not is_busy:
                    slots.append({
                        "id": candidate.isoformat(),
                        "display": candidate.strftime("%A, %B %d at %I:%M %p EST")
                    })
                    break  # one slot per day

        return slots

    except Exception as e:
        print(f"Error fetching calendar slots: {e}")
        return []


def book_appointment(slot_id, lead_name, lead_email, lead_business, lead_phone=None, appointment_type="studio_visit"):
    """
    Create a 30-minute Google Calendar event on the MWM Creations calendar.
    Tries three strategies in order, using the first that succeeds:

      1. MWM Creations calendar  + attendees + send invites
         (works when Domain-Wide Delegation is configured via GOOGLE_DELEGATE_EMAIL)
      2. MWM Creations calendar  + attendees, no email invites
         (silent attendee add — may still fail if DWD not set up)
      3. MWM Creations calendar  + no attendees
         (works when service account has WRITER access but DWD is not configured)
      4. Service account primary + no attendees
         (last-resort fallback — always works)

    Returns the event ID on success, or None on failure.
    """
    try:
        service = get_calendar_service()   # uses DWD if GOOGLE_DELEGATE_EMAIL is set
        tz = pytz.timezone(TIMEZONE)
        start_dt = datetime.fromisoformat(slot_id).astimezone(tz)
        end_dt = start_dt + timedelta(minutes=30)

        if appointment_type == "strategy_call":
            event_title = f"Strategy Call — {lead_name} ({lead_business})"
            event_desc_header = "Free 30-Minute Strategy Call with Michael Moraes / MWM Creations"
        else:
            event_title = f"Studio Visit — {lead_name} ({lead_business})"
            event_desc_header = "Studio Visit with Michael Moraes / MWM Creations Studios"

        event_base = {
            "summary": event_title,
            "description": (
                f"{event_desc_header}\n\n"
                f"Lead: {lead_name}\n"
                f"Business: {lead_business}\n"
                f"Email: {lead_email}\n"
                f"Booked via: Maya (WhatsApp Sales Agent)"
            ),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email",  "minutes": 60},
                    {"method": "popup",  "minutes": 30}
                ]
            }
        }

        # Each attempt: (calendarId, include_attendees, sendUpdates, label)
        attempts = [
            (CALENDAR_ID, True,  "all",  "MWM Creations cal + attendees + invites"),
            (CALENDAR_ID, True,  "none", "MWM Creations cal + attendees, no invites"),
            (CALENDAR_ID, False, "none", "MWM Creations cal, no attendees"),
            ("primary",   False, "none", "Service account primary, no attendees"),
        ]

        created = None
        used_attendees = False
        used_calendar = "primary"

        for cal_id, with_attendees, send_upd, label in attempts:
            event = dict(event_base)
            if with_attendees:
                event["attendees"] = [
                    {"email": MICHAEL_EMAIL},
                    {"email": lead_email}
                ]
            try:
                created = service.events().insert(
                    calendarId=cal_id,
                    body=event,
                    sendUpdates=send_upd
                ).execute()
                used_attendees = with_attendees
                used_calendar = cal_id
                print(f"✅ Booking strategy used: {label}")
                break
            except Exception as attempt_err:
                print(f"⚠️ Attempt [{label}] failed: {attempt_err}")
                continue

        if not created:
            print("❌ All booking attempts failed.")
            return None

        event_link = created.get("htmlLink", "")
        print(f"✅ Appointment booked: {created.get('id')} for {lead_name} at {start_dt}")
        print(f"📅 Calendar: {used_calendar} | Attendees included: {used_attendees}")
        print(f"📅 Event link: {event_link}")

        # ── WhatsApp notification to Michael ──────────────────────────────
        michael_phone = os.getenv("MICHAEL_PHONE")
        twilio_from   = os.getenv("TWILIO_WHATSAPP_NUMBER")
        twilio_sid    = os.getenv("TWILIO_ACCOUNT_SID")
        twilio_token  = os.getenv("TWILIO_AUTH_TOKEN")

        if michael_phone and twilio_from and twilio_sid and twilio_token:
            try:
                from twilio.rest import Client as TwilioRestClient
                twilio_rest = TwilioRestClient(twilio_sid, twilio_token)
                invite_note = (
                    "✉️ Calendar invite sent to lead."
                    if used_attendees else
                    "⚠️ Calendar invite NOT sent (DWD not yet configured — see setup guide)."
                )
                phone_line = ""
                if lead_phone:
                    clean_phone = lead_phone.replace("whatsapp:", "")
                    phone_line = f"📱 Phone: {clean_phone}\n"
                notification = (
                    f"📅 *New Studio Visit Booked via Maya!*\n\n"
                    f"👤 Name: {lead_name}\n"
                    f"🏢 Business: {lead_business}\n"
                    f"📧 Email: {lead_email}\n"
                    f"{phone_line}"
                    f"🕐 Time: {start_dt.strftime('%A, %B %d at %I:%M %p %Z')}\n\n"
                    f"{invite_note}"
                )
                twilio_rest.messages.create(
                    body=notification,
                    from_=twilio_from,
                    to=michael_phone
                )
                print(f"✅ Michael notified via WhatsApp at {michael_phone}")
            except Exception as notify_err:
                print(f"⚠️ Could not notify Michael via WhatsApp: {notify_err}")

        return created.get("id")

    except Exception as e:
        print(f"Error booking appointment: {e}")
        return None


def check_specific_slot(requested_datetime):
    """
    Check if a specific requested time is free on the MWM Creations calendar.
    Returns {"available": True, "slot_id": ..., "display": ...} or {"available": False}.
    All-day events are ignored (same logic as get_available_slots).
    """
    try:
        service = get_calendar_service()
        tz = pytz.timezone(TIMEZONE)

        # Parse the requested time; assume Eastern if no timezone info
        candidate = datetime.fromisoformat(requested_datetime)
        if candidate.tzinfo is None:
            candidate = tz.localize(candidate)
        else:
            candidate = candidate.astimezone(tz)

        # Must be a weekday between 9 AM and 4:30 PM
        if candidate.weekday() >= 5:
            return {"available": False, "reason": "weekends are not available"}
        if not (9 <= candidate.hour < 17) or (candidate.hour == 16 and candidate.minute > 30):
            return {"available": False, "reason": "outside business hours (9 AM – 5 PM EST)"}
        # Must be in the future
        if candidate <= datetime.now(tz):
            return {"available": False, "reason": "that time has already passed"}

        slot_end = candidate + timedelta(minutes=30)
        window_start = candidate - timedelta(minutes=1)
        window_end = slot_end + timedelta(minutes=1)

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=window_start.isoformat(),
            timeMax=window_end.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        for event in events_result.get("items", []):
            start_info = event.get("start", {})
            end_info = event.get("end", {})
            # Skip all-day events
            if "dateTime" not in start_info or "dateTime" not in end_info:
                continue
            ev_start = datetime.fromisoformat(start_info["dateTime"]).astimezone(tz)
            ev_end = datetime.fromisoformat(end_info["dateTime"]).astimezone(tz)
            if ev_start < slot_end and ev_end > candidate:
                return {"available": False, "reason": "that time is already booked"}

        return {
            "available": True,
            "slot_id": candidate.isoformat(),
            "display": candidate.strftime("%A, %B %d at %I:%M %p EST")
        }

    except Exception as e:
        print(f"Error checking specific slot: {e}")
        return {"available": False, "reason": "could not verify that time"}


def handle_tool_call(tool_name, tool_input, sender=None):
    """Execute a tool call and return the result as a dict."""
    if tool_name == "get_available_slots":
        slots = get_available_slots()
        if slots:
            return {"slots": slots}
        else:
            return {"error": "No available slots found in the next 7 days."}

    elif tool_name == "check_specific_slot":
        return check_specific_slot(tool_input["requested_datetime"])

    elif tool_name == "book_appointment":
        event_id = book_appointment(
            slot_id=tool_input["slot_id"],
            lead_name=tool_input["lead_name"],
            lead_email=tool_input["lead_email"],
            lead_business=tool_input["lead_business"],
            lead_phone=sender,
            appointment_type=tool_input.get("appointment_type", "studio_visit")
        )
        if event_id:
            # Update Google Sheets row with booking status
            try:
                update_booking_in_sheets(
                    sender=sender,
                    appointment_type=tool_input.get("appointment_type", "studio_visit"),
                    slot_id=tool_input["slot_id"],
                    lead_name=tool_input.get("lead_name", ""),
                    lead_email=tool_input.get("lead_email", ""),
                    lead_business=tool_input.get("lead_business", ""),
                )
            except Exception as sheets_err:
                print(f"⚠️ Sheets booking update error (non-fatal): {sheets_err}")

            # ── Notify Hub → triggers confirmation email + WhatsApp + Calendar ──
            try:
                appt_type  = tool_input.get("appointment_type", "studio_visit")
                hub_event  = "booking_confirmed_tour" if appt_type == "studio_visit" else "booking_confirmed_call"
                # Mark lead as booked so cold-lead checker skips them
                if sender and sender in lead_data:
                    lead_data[sender]["booked"] = True
                fire_hub_event(
                    event_type  = hub_event,
                    lead_name   = tool_input.get("lead_name"),
                    lead_phone  = sender,
                    lead_email  = tool_input.get("lead_email"),
                    payload     = {
                        "booking_time": tool_input["slot_id"],
                        "booking_type": appt_type,
                    },
                )
            except Exception as hub_err:
                print(f"⚠️ Hub booking event error (non-fatal): {hub_err}")

            return {"success": True, "event_id": event_id}
        else:
            return {"success": False, "error": "Could not book the appointment. Please try again."}

    return {"error": f"Unknown tool: {tool_name}"}


# ─────────────────────────────────────────────
# GOOGLE SHEETS — LEAD REPORT
# ─────────────────────────────────────────────

SHEET_HEADERS = [
    "Date", "Time", "Name", "Business", "Phone", "Email",
    "Service Interest", "Status", "Appt Date & Time", "Notes", "Follow-up ✓", "Transcript"
]

def get_sheets_service():
    """Return an authenticated Google Sheets API service client."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def ensure_monthly_tab(service, sheet_id: str, tab_name: str):
    """Create the monthly tab with headers if it doesn't exist yet. Returns the tab's sheetId (gid)."""
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    if tab_name in existing:
        return existing[tab_name]

    # Create the new tab
    result = service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab_name, "gridProperties": {"frozenRowCount": 1}}}}]}
    ).execute()
    gid = result["replies"][0]["addSheet"]["properties"]["sheetId"]

    # Write header row
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": [SHEET_HEADERS]},
    ).execute()

    # Format header (bold, dark background, white text)
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [
            {"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.18, "green": 0.18, "blue": 0.18},
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                }},
                "fields": "userEnteredFormat(textFormat,backgroundColor,foregroundColor)",
            }},
            {"autoResizeDimensions": {"dimensions": {
                "sheetId": gid, "dimension": "COLUMNS",
                "startIndex": 0, "endIndex": len(SHEET_HEADERS),
            }}},
        ]},
    ).execute()
    print(f"✅ Created new monthly tab: {tab_name}")
    return gid


def _parse_lead_fields(lead_info: str) -> dict:
    """Parse the [LEAD CAPTURED] block into a dict."""
    fields = {}
    for line in lead_info.strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip().lower()] = val.strip()
    return fields


def format_transcript(history: list) -> str:
    """Convert conversation history list into a readable transcript string."""
    lines = []
    for msg in history:
        role = "Lead" if msg.get("role") == "user" else "Maya"
        content = msg.get("content", "")
        # content can be a string or a list of blocks (tool use)
        if isinstance(content, list):
            text_parts = [
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            text = " ".join(text_parts).strip()
        else:
            text = str(content).strip()
        # Skip empty or tool-only messages
        if text:
            lines.append(f"[{role}]: {text}")
    return "\n".join(lines)


def log_lead_to_sheets(lead_info: str, sender: str, history: list = None):
    """Append a new lead row to the current month's tab."""
    if not SHEETS_LEADS_ID:
        return
    try:
        now = datetime.now(pytz.timezone(TIMEZONE))
        tab_name = now.strftime("%b %Y")   # e.g. "Mar 2026"
        fields = _parse_lead_fields(lead_info)

        clean_phone = sender.replace("whatsapp:", "").replace("+", "")

        transcript = format_transcript(history) if history else ""

        row = [
            now.strftime("%Y-%m-%d"),          # Date
            now.strftime("%I:%M %p"),           # Time
            fields.get("name", ""),             # Name
            fields.get("business", ""),         # Business
            clean_phone,                        # Phone
            fields.get("email", ""),            # Email
            fields.get("interest", ""),         # Service Interest
            "Interested — No Booking Yet",      # Status (default)
            "",                                 # Appt Date & Time (filled on booking)
            "",                                 # Notes
            "",                                 # Follow-up ✓
            transcript,                         # Full conversation transcript
        ]

        svc = get_sheets_service()
        ensure_monthly_tab(svc, SHEETS_LEADS_ID, tab_name)
        svc.spreadsheets().values().append(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        print(f"✅ Lead logged to Sheets tab '{tab_name}'")
    except Exception as e:
        print(f"⚠️ Could not log lead to Sheets (non-fatal): {e}")


def update_booking_in_sheets(sender: str, appointment_type: str, slot_id: str,
                              lead_name: str = "", lead_email: str = "", lead_business: str = ""):
    """Find the lead row by phone number and update status + appointment datetime."""
    if not SHEETS_LEADS_ID:
        return
    try:
        now = datetime.now(pytz.timezone(TIMEZONE))
        tab_name = now.strftime("%b %Y")
        clean_phone = sender.replace("whatsapp:", "").replace("+", "")

        status = "✅ Studio Visit Booked" if appointment_type == "studio_visit" else "📞 Strategy Call Booked"

        appt_dt = datetime.fromisoformat(slot_id).astimezone(pytz.timezone(TIMEZONE))
        appt_str = appt_dt.strftime("%a %b %d, %Y at %I:%M %p")

        svc = get_sheets_service()
        ensure_monthly_tab(svc, SHEETS_LEADS_ID, tab_name)

        # Read all rows and find the last one matching this phone number
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEETS_LEADS_ID,
            range=f"'{tab_name}'!A:K",
        ).execute()
        rows = result.get("values", [])

        target_row_index = None
        for i, row in enumerate(rows):
            if len(row) >= 5 and row[4] == clean_phone:  # column E = index 4 = Phone
                target_row_index = i  # keep updating to get the LAST match

        if target_row_index is not None:
            row_number = target_row_index + 1  # 1-based
            # Update Status (col H = index 8) and Appt Date & Time (col I = index 9)
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEETS_LEADS_ID,
                body={"valueInputOption": "RAW", "data": [
                    {"range": f"'{tab_name}'!H{row_number}", "values": [[status]]},
                    {"range": f"'{tab_name}'!I{row_number}", "values": [[appt_str]]},
                ]},
            ).execute()
            print(f"✅ Booking updated in Sheets row {row_number}: {status}")
        else:
            # Row not found — append a fresh complete row
            row = [
                now.strftime("%Y-%m-%d"), now.strftime("%I:%M %p"),
                lead_name, lead_business, clean_phone, lead_email, "",
                status, appt_str, "", "",
            ]
            svc.spreadsheets().values().append(
                spreadsheetId=SHEETS_LEADS_ID,
                range=f"'{tab_name}'!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
            print(f"✅ Booking row appended to Sheets (lead not found by phone)")
    except Exception as e:
        print(f"⚠️ Could not update booking in Sheets (non-fatal): {e}")


# ─────────────────────────────────────────────
# LEAD LOGGING FUNCTIONS
# ─────────────────────────────────────────────

def notify_michael_maya_lead(lead_info: str, sender: str):
    """Notify Michael via WhatsApp when Maya captures a new lead."""
    michael_phone = os.getenv("MICHAEL_PHONE")
    twilio_from   = os.getenv("TWILIO_WHATSAPP_NUMBER")
    twilio_sid    = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token  = os.getenv("TWILIO_AUTH_TOKEN")
    if not all([michael_phone, twilio_from, twilio_sid, twilio_token]):
        return
    try:
        from twilio.rest import Client as TwilioRestClient
        t = TwilioRestClient(twilio_sid, twilio_token)
        clean_phone = sender.replace("whatsapp:", "")
        body = (
            f"🔥 *New Lead Captured by Maya!*\n\n"
            f"📱 WhatsApp: {clean_phone}\n\n"
            f"{lead_info.strip()}"
        )
        t.messages.create(from_=twilio_from, to=michael_phone, body=body)
        print(f"✅ Michael notified — Maya lead: {clean_phone}")
    except Exception as e:
        print(f"⚠️ Could not notify Michael (Maya lead): {e}")


def log_lead(lead_info, sender=None, history=None):
    """Log captured leads to stdout and a writable file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n🔥 NEW LEAD CAPTURED at {timestamp}!")
    print(lead_info)
    print("=" * 50)
    # Write to /tmp which is always writable in Railway
    try:
        leads_file = "/tmp/leads.txt"
        with open(leads_file, "a") as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"NEW LEAD - {timestamp}\n")
            f.write(lead_info)
            f.write(f"\n{'='*50}\n")
    except Exception as e:
        print(f"⚠️ Could not write leads file: {e}")
    # Log to Google Sheets
    if sender:
        try:
            log_lead_to_sheets(lead_info, sender, history=history)
        except Exception as e:
            print(f"⚠️ Lead Sheets logging error (non-fatal): {e}")
    # Notify Michael via WhatsApp
    if sender:
        try:
            notify_michael_maya_lead(lead_info, sender)
        except Exception as e:
            print(f"⚠️ Lead WhatsApp notify error (non-fatal): {e}")


def extract_lead(text):
    """Extract lead info block from Claude's response."""
    pattern = r'\[LEAD CAPTURED\](.*?)\[/LEAD CAPTURED\]'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def clean_response(text):
    """Remove internal blocks before sending to WhatsApp."""
    cleaned = re.sub(r'\[LEAD CAPTURED\].*?\[/LEAD CAPTURED\]', '', text, flags=re.DOTALL)
    cleaned = cleaned.replace("[SEND_STUDIO_PHOTOS]", "")
    return cleaned.strip()


# ─────────────────────────────────────────────
# CLAUDE API WITH TOOL USE
# ─────────────────────────────────────────────

def get_claude_reply(messages, sender=None):
    """
    Call Claude (Maya) with tool use support.
    Loops until Claude returns a final text response (no more tool calls).
    Returns the final text reply and updated messages list.
    """
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        if response.stop_reason == "tool_use":
            # Collect text + tool calls from this assistant turn
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"🔧 Tool call: {block.name} | Input: {block.input}")
                    result = handle_tool_call(block.name, block.input, sender=sender)
                    print(f"🔧 Tool result: {result}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })

            # Append assistant's tool-use turn and the tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Final text response — extract the text
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            # Append final assistant reply to history (text only for storage)
            messages.append({"role": "assistant", "content": final_text})
            return final_text, messages


# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────

@app.route("/audio/<path:filename>")
def serve_audio(filename):
    """Serve TTS-generated audio files stored in /tmp/audio."""
    return send_from_directory("/tmp/audio", filename)


def _extract_gabriela_followups(text: str) -> list[str]:
    """Return URLs and phone numbers found in Gabriela's reply to send as follow-up texts."""
    items = []
    if re.search(r'videoproductionplans\.com/expo2026', text, re.IGNORECASE):
        items.append('https://www.videoproductionplans.com/expo2026')
    if re.search(r'videoproductionplans\.com/book-?studio', text, re.IGNORECASE):
        items.append('https://www.videoproductionplans.com/book-studio')
    # Michael's direct WhatsApp number — send as a clickable contact
    if re.search(r'813.*?503.*?1224|8135031224', text):
        items.append('+1 (813) 503-1224')
    return items


def _send_whatsapp_api(to: str, body: str = None, media_url: str = None):
    """Send a WhatsApp message via Twilio REST API (used for async replies)."""
    sid    = os.getenv("TWILIO_ACCOUNT_SID")
    token  = os.getenv("TWILIO_AUTH_TOKEN")
    from_  = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14078716473")
    if not from_.startswith("whatsapp:"):
        from_ = f"whatsapp:{from_}"
    if not sid or not token:
        print("⚠️ Twilio credentials missing — cannot send async message")
        return
    try:
        tc = TwilioRestClient(sid, token)
        kwargs = {"from_": from_, "to": to}
        if media_url:
            kwargs["media_url"] = [media_url]
            kwargs["body"] = ""
        else:
            kwargs["body"] = body or ""
        msg = tc.messages.create(**kwargs)
        print(f"✅ Async message sent: {msg.sid}")
    except Exception as e:
        print(f"❌ Async send failed: {e}")


def fire_hub_event(event_type, lead_name=None, lead_phone=None, lead_email=None,
                   payload=None, notes=None):
    """
    Fire an event to the MWM Agent Hub — non-blocking background thread.
    The Hub then handles: email confirmation, WhatsApp reminder, Calendar event, etc.
    """
    hub_url = os.getenv("AGENT_HUB_URL", "")
    hub_key = os.getenv("AGENT_HUB_API_KEY", "")
    if not hub_url or not hub_key:
        print("⚠️ AGENT_HUB_URL or AGENT_HUB_API_KEY not set — Hub event skipped")
        return

    # Normalize phone: Hub expects +1XXXXXXXXXX (no whatsapp: prefix)
    clean_phone = lead_phone or ""
    clean_phone = clean_phone.replace("whatsapp:", "")
    if clean_phone and not clean_phone.startswith("+"):
        clean_phone = "+" + clean_phone

    def _send():
        import urllib.request, urllib.error
        body = json.dumps({
            "from_agent":  "maya",
            "event_type":  event_type,
            "lead_name":   lead_name,
            "lead_phone":  clean_phone,
            "lead_email":  lead_email,
            "payload":     payload or {},
            "notes":       notes,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{hub_url}/event",
            data=body,
            headers={"Content-Type": "application/json", "X-Api-Key": hub_key},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                print(f"✅ Hub event fired: [{event_type}] | handlers triggered: {result.get('handlers_triggered', 0)}")
        except urllib.error.HTTPError as e:
            print(f"⚠️ Hub event [{event_type}] HTTP {e.code}: {e.read().decode()}")
        except Exception as e:
            print(f"⚠️ Hub event [{event_type}] failed: {e}")

    threading.Thread(target=_send, daemon=True).start()


def _process_gabriela_audio_async(sender: str, media_url: str):
    """Background thread: transcribe voice note, get Gabriela reply, send TTS via Twilio API.

    Runs outside the Twilio webhook request context so there is no 15-second timeout.
    """
    try:
        # ── 1. Transcribe ────────────────────────────────────────────────────
        try:
            incoming_msg = transcribe_audio(media_url, language="pt")
            print(f"📝 Async transcription: {incoming_msg!r}")
        except Exception as trans_err:
            print(f"❌ Async transcription failed: {trans_err}")
            _send_whatsapp_api(
                sender,
                body="Desculpe, não consegui ouvir seu áudio agora. Pode me enviar a mensagem por texto? 🙏"
            )
            return

        # ── 2. Init / update history ─────────────────────────────────────────
        if sender not in gabriela_history:
            gabriela_history[sender] = []
        gabriela_history[sender].append({"role": "user", "content": incoming_msg})
        if len(gabriela_history[sender]) > 20:
            gabriela_history[sender] = gabriela_history[sender][-20:]

        # ── 3. Get Gabriela reply ─────────────────────────────────────────────
        try:
            reply, updated = get_gabriela_reply(gabriela_history[sender])
            gabriela_history[sender] = updated
        except Exception as e:
            print(f"❌ Async Gabriela error: {e}")
            _send_whatsapp_api(
                sender,
                body="Desculpe, estou com uma instabilidade técnica. Por favor, tente novamente em instantes. 🙏"
            )
            return

        # ── 4. Notify Michael if interest detected ────────────────────────────
        try:
            empresa, interesse = extract_expo_interest(reply)
            if empresa or interesse:
                notify_michael_expo_interest(sender, empresa, interesse, incoming_msg)
        except Exception as notify_err:
            print(f"⚠️ Expo notify error (non-fatal): {notify_err}")

        clean_reply = clean_gabriela_response(reply)

        # ── 5. TTS → send audio; fall back to text if TTS fails ───────────────
        audio_url = None
        try:
            audio_url = generate_audio_reply(clean_reply)
        except Exception as tts_err:
            print(f"⚠️ Async TTS failed, falling back to text: {tts_err}")

        if audio_url:
            _send_whatsapp_api(sender, media_url=audio_url)
            print(f"🔊 Async audio reply sent to {sender}")
        else:
            _send_whatsapp_api(sender, body=clean_reply)
            print(f"📝 Async text reply sent to {sender} (TTS unavailable)")

        # ── 6. Follow-up texts: URLs and phone numbers ────────────────────────
        # Gabriela's audio says "vou te enviar o link/número por texto" —
        # these messages deliver on that promise.
        for item in _extract_gabriela_followups(clean_reply):
            _send_whatsapp_api(sender, body=item)
            print(f"🔗 Sent follow-up text to {sender}: {item}")

    except Exception as e:
        print(f"❌ Unexpected async processing error for {sender}: {e}")
        try:
            _send_whatsapp_api(
                sender,
                body="Desculpe, estou com uma instabilidade técnica. Por favor, tente novamente. 🙏"
            )
        except Exception:
            pass


@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender       = request.values.get("From", "")
    num_media    = int(request.values.get("NumMedia", 0))

    print(f"📩 Message from {sender}: {incoming_msg!r} | media={num_media}")

    # ── Audio message handling ─────────────────────────────────────────────
    # WhatsApp voice notes arrive with an empty Body and MediaContentType0=audio/*
    was_audio = False  # track whether the incoming message was a voice note

    if num_media > 0:
        content_type = request.values.get("MediaContentType0", "")
        media_url    = request.values.get("MediaUrl0", "")

        if "audio" in content_type and media_url:
            print(f"🎙️ Voice note received — ContentType: {content_type}")

            if is_expo_lead(sender):
                # ── ASYNC path for Gabriela voice notes ────────────────────
                # Return empty TwiML immediately to beat Twilio's 15s timeout.
                # All heavy work (Whisper + AI + ElevenLabs TTS) happens in a
                # background thread which sends the reply via Twilio REST API.
                print(f"⏱️ Launching async Gabriela audio processing for {sender}")
                threading.Thread(
                    target=_process_gabriela_audio_async,
                    args=(sender, media_url),
                    daemon=True
                ).start()
                return str(MessagingResponse())  # empty TwiML — instant response

            # ── Sync path for Maya (text reply, no TTS — fast enough) ──────
            try:
                incoming_msg = transcribe_audio(media_url, language=None)
                was_audio = True  # transcription succeeded — track for potential audio reply
            except Exception as trans_err:
                print(f"❌ Transcription failed: {trans_err}")
                twiml = MessagingResponse()
                twiml.message(
                    "Sorry, I couldn't process your voice message. "
                    "Could you send it as text instead? 🙏"
                )
                return str(twiml)

        elif not incoming_msg:
            # Non-audio media (image, document, sticker…) with no text — acknowledge gracefully
            twiml = MessagingResponse()
            if is_expo_lead(sender):
                twiml.message(
                    "Recebi seu arquivo! 😊 Posso te ajudar com os pacotes de vídeo da Expo Brazil?"
                )
            else:
                twiml.message("Thanks for the file! How can I help you today? 😊")
            return str(twiml)

    # ── Route: Expo Brazil lead → Gabriela, everyone else → Maya ──────────
    if is_expo_lead(sender):
        print(f"🇧🇷 Routing to GABRIELA (Expo Brazil lead)")

        if sender not in gabriela_history:
            gabriela_history[sender] = []

        gabriela_history[sender].append({"role": "user", "content": incoming_msg})

        if len(gabriela_history[sender]) > 20:
            gabriela_history[sender] = gabriela_history[sender][-20:]

        try:
            reply, updated = get_gabriela_reply(gabriela_history[sender])
            gabriela_history[sender] = updated

            # Check for interest signal and notify Michael
            try:
                empresa, interesse = extract_expo_interest(reply)
                if empresa or interesse:
                    notify_michael_expo_interest(sender, empresa, interesse, incoming_msg)
            except Exception as notify_err:
                print(f"⚠️ Expo notify error (non-fatal): {notify_err}")

            clean_reply = clean_gabriela_response(reply)

            # ── Audio reply: if lead sent a voice note, Gabriela replies with one too ──
            if was_audio:
                try:
                    audio_url = generate_audio_reply(clean_reply)
                    if audio_url:
                        twiml = MessagingResponse()
                        msg = twiml.message("")
                        msg.media(audio_url)
                        print(f"🔊 Sending audio reply to {sender}")
                        return str(twiml)
                    # audio_url is None (env var missing) — fall through to text
                except Exception as tts_err:
                    print(f"⚠️ TTS failed, falling back to text: {tts_err}")

        except Exception as e:
            print(f"❌ Gabriela error: {e}")
            clean_reply = "Desculpe, estou com uma instabilidade técnica. Por favor, tente novamente em instantes. 🙏"

    else:
        # ── Maya path — ASYNC to beat Twilio's 15s timeout ──────────────
        print(f"🤖 Routing to MAYA (async)")

        if sender not in conversation_history:
            conversation_history[sender] = []

        conversation_history[sender].append({"role": "user", "content": incoming_msg})

        # ── Stamp last_message_time for cold-lead detection ──────────────
        if sender not in lead_data:
            lead_data[sender] = {}
        lead_data[sender]["last_message_time"] = datetime.now(pytz.timezone(TIMEZONE))

        if len(conversation_history[sender]) > 20:
            conversation_history[sender] = conversation_history[sender][-20:]

        # Snapshot history for the background thread
        history_snapshot = list(conversation_history[sender])

        def process_maya(snap, sndr):
            sid    = os.getenv("TWILIO_ACCOUNT_SID")
            token  = os.getenv("TWILIO_AUTH_TOKEN")
            from_  = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14078716473")
            if not from_.startswith("whatsapp:"):
                from_ = f"whatsapp:{from_}"
            to_wa = sndr if sndr.startswith("whatsapp:") else f"whatsapp:{sndr}"
            try:
                reply, updated_history = get_claude_reply(snap, sndr)
                conversation_history[sndr] = updated_history

                try:
                    lead_info = extract_lead(reply)
                    if lead_info:
                        log_lead(lead_info, sender=sndr, history=updated_history)
                        # ── Save name/email for cold-lead detection ───────
                        try:
                            fields = _parse_lead_fields(lead_info)
                            if sndr not in lead_data:
                                lead_data[sndr] = {}
                            lead_data[sndr].update({
                                "name":  fields.get("name", lead_data[sndr].get("name", "")),
                                "email": fields.get("email", lead_data[sndr].get("email", "")),
                            })
                        except Exception:
                            pass
                except Exception as lead_err:
                    print(f"⚠️ Lead logging error (non-fatal): {lead_err}")

                send_photos = "[SEND_STUDIO_PHOTOS]" in reply
                clean_reply = clean_response(reply)

            except Exception as e:
                print(f"❌ Maya error: {e}")
                clean_reply = "Sorry, I'm having a technical issue right now. Please try again in a moment."
                send_photos = False

            # Send reply via Twilio REST API
            if sid and token:
                try:
                    tc = TwilioRestClient(sid, token)
                    tc.messages.create(from_=from_, to=to_wa, body=clean_reply)
                    print(f"✅ Maya reply sent to {to_wa}")
                except Exception as send_err:
                    print(f"❌ Maya send error: {send_err}")

                # Send studio photos if triggered
                if send_photos:
                    try:
                        for photo_url in STUDIO_PHOTOS:
                            tc.messages.create(from_=from_, to=to_wa, media_url=[photo_url])
                        print(f"✅ Studio photos sent to {to_wa}")
                    except Exception as photo_err:
                        print(f"⚠️ Could not send studio photos (non-fatal): {photo_err}")

        threading.Thread(target=process_maya, args=(history_snapshot, sender), daemon=True).start()
        return str(MessagingResponse())  # empty TwiML — instant response to Twilio


@app.route("/send-intro", methods=["POST"])
def send_intro():
    """
    Proactively send the expo_brazil_intro WhatsApp template to a lead.

    Expected JSON body:
        {
            "phone": "+5511999999999",   # lead's WhatsApp number (E.164 format)
            "name":  "Carlos"            # lead's first name (fills {{1}} variable)
        }

    The template must be approved by Meta before this works for business-initiated messages.
    Template SID: HXed308a5431d011c53361498f4cd18973
    Template name: expo_brazil_intro (Portuguese BR)
    """
    import json as _json
    from flask import jsonify

    data = request.get_json(force=True, silent=True) or {}
    phone = data.get("phone", "").strip()
    name  = data.get("name", "").strip() or "amigo"

    if not phone:
        return jsonify({"error": "Missing 'phone' field"}), 400

    # Normalize to WhatsApp format
    to_wa = phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"

    sid    = os.getenv("TWILIO_ACCOUNT_SID")
    token  = os.getenv("TWILIO_AUTH_TOKEN")
    from_  = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14078716473")
    if not from_.startswith("whatsapp:"):
        from_ = f"whatsapp:{from_}"

    if not sid or not token:
        return jsonify({"error": "Twilio credentials not configured"}), 500

    try:
        tc = TwilioRestClient(sid, token)
        msg = tc.messages.create(
            from_=from_,
            to=to_wa,
            content_sid=data.get("content_sid", "HXed308a5431d011c53361498f4cd18973"),
            content_variables=_json.dumps({"1": name}),
        )
        print(f"✅ Intro sent to {to_wa} (name={name}): {msg.sid}")
        return jsonify({"success": True, "sid": msg.sid, "to": to_wa, "name": name}), 200
    except Exception as e:
        print(f"❌ send-intro failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return "MWM Creations Sales Agent (Maya + Gabriela) is running! ✅"


# ─────────────────────────────────────────────
# COLD-LEAD DETECTION — Background Thread
# Checks every hour. Fires lead_cold event to Hub for any lead
# silent 48+ hours who hasn't booked and hasn't already been flagged.
# ─────────────────────────────────────────────

def _cold_lead_checker():
    import time
    print("❄️  Cold-lead checker started (polls every hour, fires at 48h silence)")
    time.sleep(3600)  # First check after 1 hour so startup noise settles
    while True:
        try:
            now = datetime.now(pytz.timezone(TIMEZONE))
            for phone, data in list(lead_data.items()):
                if data.get("booked") or data.get("cold_fired"):
                    continue
                last_msg = data.get("last_message_time")
                if not last_msg:
                    continue
                hours_silent = (now - last_msg).total_seconds() / 3600
                if hours_silent >= 48:
                    name  = data.get("name") or ""
                    email = data.get("email") or ""
                    print(f"❄️  Cold lead detected: {phone} ({int(hours_silent)}h silent) — firing Hub event")
                    fire_hub_event(
                        event_type = "lead_cold",
                        lead_name  = name or None,
                        lead_phone = phone,
                        lead_email = email or None,
                        payload    = {"hours_silent": int(hours_silent)},
                        notes      = f"Lead has not replied in {int(hours_silent)} hours",
                    )
                    lead_data[phone]["cold_fired"] = True
        except Exception as e:
            print(f"⚠️  Cold-lead checker error: {e}")
        time.sleep(3600)  # Check again in 1 hour

threading.Thread(target=_cold_lead_checker, daemon=True).start()


if __name__ == "__main__":
    print("Starting MWM Creations Sales Agent — Maya")
    print("Server running on http://127.0.0.1:5000")
    app.run(debug=True, host="127.0.0.1", port=5000)
