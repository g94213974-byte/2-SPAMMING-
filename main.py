#!/usr/bin/env python3
"""
Telegram Mass Messaging Bot v7.0 FINAL ✨
- v6.4 features (special msg per account, phone OTP fix, targeted broadcast)
- v7: 20s pre-expiry warning + auto-remove expired admins
- v7: Expired user → "bot deleted" screen with PLAN buttons (owner-customizable)
- v7: QR payment flow → screenshot → owner Accept/Reject/Block
- v7: Referral system (20% commission, balance-based purchase)
"""
import sys, os, asyncio, random, logging, json, threading, httpx, re, uuid
from datetime import datetime, timedelta
from telethon import TelegramClient, errors, functions
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.errors import (
    FloodWaitError, SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, UserRestrictedError, AuthKeyUnregisteredError,
    UserDeactivatedError, UserDeactivatedBanError)
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from flask import Flask

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    force=True, handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
API_ID_1 = int(os.environ.get("API_ID_1", "0")); API_HASH_1 = os.environ.get("API_HASH_1", ""); SESSION_1 = os.environ.get("SESSION_1", "")
API_ID_2 = int(os.environ.get("API_ID_2", "0")); API_HASH_2 = os.environ.get("API_HASH_2", ""); SESSION_2 = os.environ.get("SESSION_2", "")
API_ID_3 = int(os.environ.get("API_ID_3", "0")); API_HASH_3 = os.environ.get("API_HASH_3", ""); SESSION_3 = os.environ.get("SESSION_3", "")

DYNAMIC_ACCOUNTS_FILE = "dynamic_accounts.json"
AUTH_SESSIONS_FILE = "auth_sessions.json"
ADMINS_FILE = "admins.json"
PROFILE_FILE = "profile_configs.json"
NAME_FILE = "user_names.json"
DEFAULT_PROFILE_KEY = "__default__"
USER_SPEED_FILE = "user_speed.json"
SPECIAL_MSG_FILE = "special_msgs.json"
MESSAGE = os.environ.get("MESSAGE", "𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖")
MIN_INTERVAL = int(os.environ.get("MIN_INTERVAL", "6"))
MAX_INTERVAL = int(os.environ.get("MAX_INTERVAL", "10"))
CYCLE_WAIT = int(os.environ.get("CYCLE_WAIT", "45"))
EXPIRED_MSG = "Your plan has expired. Contact admin 👉 @G18GamerBacko to buy a new one."

running_tasks, stop_flags, account_clients, account_stats, phone_login_states, display_names = {}, {}, {}, {}, {}, {}
data_file = "bot_data.json"
SHOW_START_TO_OTHERS = True

# ================= v7 STORE / PAYMENT / REFERRAL =================
PLANS_FILE = "plans.json"
PAYMENTS_FILE = "payments.json"
REFS_FILE = "referrals.json"
QR_FILE = "qr_config.json"
BALANCES_FILE = "balances.json"
BLOCKED_FILE = "blocked_users.json"
WARN_BEFORE_SEC = 20
warned_users = set()

def load_json(fname, default):
    try: return json.load(open(fname)) if os.path.exists(fname) else default
    except: return default
def save_json(fname, data):
    try: json.dump(data, open(fname, 'w'), indent=2)
    except: pass
def load_plans(): return load_json(PLANS_FILE, [])
def save_plans(p): save_json(PLANS_FILE, p)
def load_qr(): return load_json(QR_FILE, {})
def save_qr(d): save_json(QR_FILE, d)
def is_blocked(uid): return uid in load_json(BLOCKED_FILE, [])
def get_balance(uid): return float(load_json(BALANCES_FILE, {}).get(str(uid), 0))
def add_balance(uid, amt):
    b = load_json(BALANCES_FILE, {}); b[str(uid)] = get_balance(uid) + amt
    save_json(BALANCES_FILE, b)
def get_ref_code(uid):
    r = load_json(REFS_FILE, {})
    if str(uid) not in r:
        r[str(uid)] = {'code': uuid.uuid4().hex[:8], 'referred': [], 'earnings': 0.0}
        save_json(REFS_FILE, r)
    return r[str(uid)]['code']
def find_referrer_by_code(code):
    r = load_json(REFS_FILE, {})
    for uid_s, v in r.items():
        if v.get('code') == code: return int(uid_s)
    return None
def get_referrer_of(uid):
    r = load_json(REFS_FILE, {})
    for uid_s, v in r.items():
        if uid_s != str(uid) and uid in v.get('referred', []): return int(uid_s)
    return None
def set_referred(user_id, referrer_id):
    if user_id == referrer_id: return
    r = load_json(REFS_FILE, {})
    get_ref_code(user_id); get_ref_code(referrer_id)
    v = r[str(referrer_id)]
    if user_id not in v.setdefault('referred', []):
        v['referred'].append(user_id); save_json(REFS_FILE, r)

async def activate_plan(user_id, days, plan_name="plan"):
    nd = datetime.now() + timedelta(days=days)
    admins = load_admins(); a = get_admin(user_id)
    if a is None:
        admins.append({'user_id': user_id, 'expires_at': nd.isoformat(), 'added_at': datetime.now().isoformat(),
                       'updated_at': datetime.now().isoformat(), 'max_accounts': DEFAULT_ADMIN_LIMIT})
    else:
        cur = None
        try: cur = datetime.fromisoformat(a['expires_at']) if a.get('expires_at') else None
        except: cur = None
        rem = (cur - datetime.now()) if (cur and cur > datetime.now()) else timedelta(0)
        a['expires_at'] = (datetime.now() + rem + timedelta(days=days)).isoformat()
        a['updated_at'] = datetime.now().isoformat()
        for i, x in enumerate(admins):
            if x['user_id'] == user_id: admins[i] = a
    save_admins(admins)
    warned_users.discard(user_id)
    gg = get_admin(user_id)
    try:
        await notify_user(user_id, f"✅ *Payment confirmed!*\n\n💎 Plan: {plan_name}\n⏳ Your validity: {remaining_time_str(gg.get('expires_at') if gg else None)}")
    except: pass

def expired_panel_keyboard():
    kb = []
    for p in load_plans():
        kb.append([InlineKeyboardButton(p['btn_name'], callback_data=f"buy_{p['plan_id']}")])
    kb.append([InlineKeyboardButton("💰 Buy with referral balance", callback_data='ref_buy_menu')])
    kb.append([InlineKeyboardButton("👥 My Referral", callback_data='ref_menu')])
    return InlineKeyboardMarkup(kb)

def expired_panel_text():
    lines = ["🚫 *Bot access deleted!*\n\nYour plan has expired.\nContact admin 👉 @G18GamerBacko\n\n💎 *Available Plans:*"]
    for p in load_plans():
        lines.append(f"\n▫️ {p['name']} — ₹{p['price']} / {p['days']}d")
    return "\n".join(lines)

def load_names():
    try: return json.load(open(NAME_FILE)) if os.path.exists(NAME_FILE) else {}
    except: return {}
def save_names(d):
    try: json.dump(d, open(NAME_FILE, 'w'), indent=2)
    except: pass
def record_user_info(uid, first="", last="", username=""):
    d = load_names()
    old = d.get(str(uid), {})
    full = (str(first or '').strip())
    if last: full = f"{full} {last}".strip()
    d[str(uid)] = {'name': (full or old.get('name','')),
                   'username': (username or old.get('username',''))}
    save_names(d)
def admin_label(uid):
    info = load_names().get(str(uid))
    if info and info.get('name'):
        return f"{info['name']} (ID: {uid})"
    return f"ID: {uid}"
def get_names_short(uid):
    info = load_names().get(str(uid))
    if info and info.get('name'):
        return info['name'][:14]
    return str(uid)

def load_user_speeds():
    try: return json.load(open(USER_SPEED_FILE)) if os.path.exists(USER_SPEED_FILE) else {}
    except: return {}
def save_user_speeds(data):
    try: json.dump(data, open(USER_SPEED_FILE, 'w'), indent=2)
    except: pass
def speed_for(uid):
    s = load_user_speeds().get(str(uid))
    if not s: return (MIN_INTERVAL, MAX_INTERVAL, CYCLE_WAIT)
    return (s.get('min', MIN_INTERVAL), s.get('max', MAX_INTERVAL), s.get('cycle', CYCLE_WAIT))
def set_speed(uid, min_i=None, max_i=None, cycle=None):
    d = load_user_speeds(); s = d.setdefault(str(uid), {})
    if min_i is not None: s['min'] = min_i
    if max_i is not None: s['max'] = max_i
    if cycle is not None: s['cycle'] = cycle
    save_user_speeds(d)

def load_special_msgs():
    try: return json.load(open(SPECIAL_MSG_FILE)) if os.path.exists(SPECIAL_MSG_FILE) else {}
    except: return {}
def save_special_msgs(d):
    try: json.dump(d, open(SPECIAL_MSG_FILE, 'w'), indent=2)
    except: pass
def get_special_msg(aid):
    return load_special_msgs().get(str(aid)) or ""
def set_special_msg(aid, msg):
    d = load_special_msgs()
    if msg: d[str(aid)] = msg
    else: d.pop(str(aid), None)
    save_special_msgs(d)
def acc_by_id(aid):
    for a in get_all_accounts():
        if a['id'] == aid: return a
    return None
def get_display_name_by_id(aid):
    a = acc_by_id(aid)
    return get_display_name(a) if a else aid

try:
    _e = os.environ.get("ADMIN_ACCOUNT_LIMIT", "").strip()
    DEFAULT_ADMIN_LIMIT = int(_e) if _e else None
except Exception:
    DEFAULT_ADMIN_LIMIT = None
BACK_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='back_main')]])

def broadcast_targets():
    ids = [OWNER_ID]
    for a in load_admins():
        if is_valid_admin(a['user_id']) and a['user_id'] != OWNER_ID:
            ids.append(a['user_id'])
    return list(dict.fromkeys(ids))

def is_owner(u): return u == OWNER_ID
def load_admins():
    try: return json.load(open(ADMINS_FILE)) if os.path.exists(ADMINS_FILE) else []
    except: return []
def save_admins(x):
    try: json.dump(x, open(ADMINS_FILE, 'w'), indent=2)
    except: pass
def replace_admin(target, new_entry):
    admins = load_admins()
    for i, a in enumerate(admins):
        if a['user_id'] == target:
            admins[i] = new_entry; break
    save_admins(admins)
def get_admin(u):
    for a in load_admins():
        if a['user_id'] == u: return a
    return None
def is_valid_admin(u):
    a = get_admin(u)
    if not a: return False
    exp = a.get('expires_at')
    if not exp: return True
    try: return datetime.fromisoformat(exp) > datetime.now()
    except: return False
def remaining_time_str(e):
    if not e: return "♾️ Permanent"
    try: d = datetime.fromisoformat(e) - datetime.now()
    except: return "?"
    if d.total_seconds() <= 0: return "⛔ EXPIRED"
    days, s = d.days, d.seconds
    h, m = s // 3600, (s % 3600) // 60
    p = []
    if days: p.append(f"{days}d")
    if h: p.append(f"{h}h")
    if m: p.append(f"{m}m")
    return " ".join(p) + " left" if p else "<1s"

def parse_duration(t):
    t = t.strip().lower()
    if t in ('perm','permanent','inf','unlimited','infinite'): return None
    for a, b in [('seconds','s'),('second','s'),('secs','s'),('sec','s'),
                 ('minutes','m'),('minute','m'),('mins','m'),('min','m'),
                 ('hours','h'),('hour','h'),('hrs','h'),('hr','h'),
                 ('days','d'),('day','d'),
                 ('weeks','w'),('week','w')]:
        t = t.replace(a, b)
    total, found = timedelta(), False
    for num, unit in re.findall(r'(\d+)\s*([dhms w])?', t + ' '):
        if not num.strip(): continue
        n = int(num)
        unit = (unit or 'm').strip()
        if unit == 'd': total += timedelta(days=n)
        elif unit == 'h': total += timedelta(hours=n)
        elif unit == 'w': total += timedelta(days=n*7)
        elif unit == 's': total += timedelta(seconds=n)
        else: total += timedelta(minutes=n)
        found = True
    if not found: raise ValueError("bad duration")
    return datetime.now() + total

def parse_admin_cmd(t):
    pr = t.strip().split(None, 1)
    if not pr: raise ValueError("need USER_ID")
    uid = int(pr[0]); rest = pr[1].strip() if len(pr) > 1 else 'perm'
    op = '+'
    if rest and rest[0] in ('+', '-', '='):
        op = rest[0]; rest = rest[1:].strip()
    if not rest or rest.lower() in ('perm','permanent','inf','unlimited','infinite'):
        return uid, op, None
    return uid, op, parse_duration(rest)

def gen_unique_id(p, o): return f"{p}_{o}_{uuid.uuid4().hex[:6]}"
def messages_file_for(u): return "messages.json" if is_owner(u) else f"messages_{u}.json"
def load_messages_for(u):
    f = messages_file_for(u)
    try: return json.load(open(f)) if os.path.exists(f) else []
    except: return []
def save_messages_for(u, m):
    try: json.dump(m, open(messages_file_for(u), 'w'), indent=2)
    except: pass
def get_random_message_for(u):
    m = load_messages_for(u)
    return random.choice(m) if m else MESSAGE

def load_profiles():
    try: return json.load(open(PROFILE_FILE)) if os.path.exists(PROFILE_FILE) else {}
    except: return {}
def save_profiles(p):
    try: json.dump(p, open(PROFILE_FILE, 'w'), indent=2)
    except: pass
def get_default_profile(): return load_profiles().get(DEFAULT_PROFILE_KEY, {})
def save_default_profile(cfg):
    p = load_profiles(); p[DEFAULT_PROFILE_KEY] = cfg; save_profiles(p)

def load_auth_sessions():
    try: return json.load(open(AUTH_SESSIONS_FILE)) if os.path.exists(AUTH_SESSIONS_FILE) else []
    except: return []
def save_auth_sessions(s):
    try: json.dump(s, open(AUTH_SESSIONS_FILE, 'w'), indent=2)
    except: pass

ENV_ACCOUNTS = []
acc_configs = [('acc1',API_ID_1,API_HASH_1,SESSION_1),('acc2',API_ID_2,API_HASH_2,SESSION_2),('acc3',API_ID_3,API_HASH_3,SESSION_3)]
async def init_env_accounts():
    for acc_id, api_id, api_hash, session in acc_configs:
        if api_id and api_hash and session:
            try:
                c = TelegramClient(StringSession(session), api_id, api_hash, receive_updates=False)
                await c.start(); me = await c.get_me()
                n = me.first_name or f"User{me.id}"; await c.disconnect()
                ENV_ACCOUNTS.append({'id':acc_id,'name':n,'api_id':api_id,'api_hash':api_hash,'session':session,
                                     'type':'env','phone':getattr(me,'phone',''),'owner_id':OWNER_ID})
                display_names[acc_id] = n
            except Exception as e:
                print(f"failed {acc_id}: {str(e)[:50]}", flush=True)
            await asyncio.sleep(1)

def load_dynamic_accounts():
    try: return json.load(open(DYNAMIC_ACCOUNTS_FILE)) if os.path.exists(DYNAMIC_ACCOUNTS_FILE) else []
    except: return []
def save_dynamic_accounts(a):
    try: json.dump(a, open(DYNAMIC_ACCOUNTS_FILE, 'w'), indent=2)
    except: pass

def get_all_accounts(user_id=None):
    dyn = load_dynamic_accounts()
    auth = []
    for s in load_auth_sessions():
        auth.append({'id':s['id'],'name':s.get('name',f"User_{s.get('user_id','?')}"),'api_id':s['api_id'],
                     'api_hash':s['api_hash'],'session':s['session_string'],'type':'phone_auth',
                     'phone':s.get('phone',''),'owner_id':s.get('owner_id',OWNER_ID)})
    accs = ENV_ACCOUNTS + dyn + auth
    if user_id is None or user_id == OWNER_ID: return accs
    return [a for a in accs if a.get('owner_id') == user_id]

def get_display_name(acc): return display_names.get(acc.get('id')) or acc.get('name') or str(acc.get('id'))
def preload_display_names(accs):
    for acc in accs: display_names.setdefault(acc.get('id'), acc.get('name'))
def persist_rename(acc_id, new_name):
    if not new_name: return
    display_names[acc_id] = new_name
    for fname in (DYNAMIC_ACCOUNTS_FILE, AUTH_SESSIONS_FILE):
        if not os.path.exists(fname): continue
        try:
            data = json.load(open(fname)); ch = False
            for it in data:
                if it.get('id') == acc_id and it.get('name') != new_name:
                    it['name'] = new_name; ch = True
            if ch: json.dump(data, open(fname, 'w'), indent=2)
        except: pass
    for acc in ENV_ACCOUNTS:
        if acc['id'] == acc_id: acc['name'] = new_name

def add_dynamic_account(name, ss, owner_id, api_id=0, api_hash=""):
    accs = load_dynamic_accounts()
    for a in accs:
        if a['session'] == ss: return False, "Session already exists!"
    nid = gen_unique_id("acc_dyn", owner_id)
    accs.append({'id':nid,'name':name,'api_id':api_id or API_ID_1,'api_hash':api_hash or API_HASH_1,
                 'session':ss,'type':'dynamic','owner_id':owner_id})
    save_dynamic_accounts(accs); display_names[nid] = name
    return True, nid

def remove_account_by_id(aid):
    global ENV_ACCOUNTS
    dyn = load_dynamic_accounts()
    for i, a in enumerate(dyn):
        if a['id'] == aid: dyn.pop(i); save_dynamic_accounts(dyn); display_names.pop(aid,None); return True
    au = load_auth_sessions()
    for i, a in enumerate(au):
        if a['id'] == aid: au.pop(i); save_auth_sessions(au); display_names.pop(aid,None); return True
    for i, a in enumerate(ENV_ACCOUNTS):
        if a['id'] == aid: ENV_ACCOUNTS.pop(i); display_names.pop(aid,None); return True
    return False

def admin_max_accounts(u):
    if is_owner(u): return None
    a = get_admin(u)
    if a and a.get('max_accounts') is not None: return int(a['max_accounts'])
    return DEFAULT_ADMIN_LIMIT
def owner_acc_count(u): return sum(1 for a in get_all_accounts() if a.get('owner_id') == u)
def account_limit_reached(u):
    if is_owner(u): return False, ""
    cap = admin_max_accounts(u)
    if cap is None: return False, ""
    if owner_acc_count(u) >= cap: return True, f"❌ Account limit reached ({owner_acc_count(u)}/{cap})!"
    return False, ""
def refresh_account_stats(user_id=None):
    for a in get_all_accounts(user_id):
        aid = a['id']
        if aid not in account_stats:
            account_stats[aid] = {'sent':0,'running':False,'failed_channels':[]}
            stop_flags[aid] = False

web_app = Flask(__name__)
@web_app.route("/")
def home():
    all_a = get_all_accounts()
    run = sum(1 for a in all_a if account_stats.get(a['id'],{}).get('running',False))
    sent = sum(account_stats.get(a['id'],{}).get('sent',0) for a in all_a)
    return f"v7.0 FINAL ✨ | Accounts:{len(all_a)} | Active:{run}/{len(all_a)} | Sent:{sent} | Admins:{len(load_admins())}"
@web_app.route("/health")
def health(): return "OK", 200
def run_flask(): web_app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)), debug=False, use_reloader=False)

def load_data():
    global MESSAGE, MIN_INTERVAL, MAX_INTERVAL, CYCLE_WAIT
    if os.path.exists(data_file):
        try:
            d = json.load(open(data_file))
            MESSAGE = d.get('message', MESSAGE); MIN_INTERVAL = d.get('min_interval', MIN_INTERVAL)
            MAX_INTERVAL = d.get('max_interval', MAX_INTERVAL); CYCLE_WAIT = d.get('cycle_wait', CYCLE_WAIT)
        except: pass
def save_data():
    try:
        json.dump({'message':MESSAGE,'min_interval':MIN_INTERVAL,'max_interval':MAX_INTERVAL,
                   'cycle_wait':CYCLE_WAIT,'show_start_to_others':SHOW_START_TO_OTHERS}, open(data_file,'w'), indent=2)
    except: pass

async def get_client(acc):
    aid = acc['id']; old = account_clients.get(aid)
    if old is not None:
        try:
            if old.is_connected(): return old
            await old.disconnect()
        except: pass
        del account_clients[aid]
    c = TelegramClient(StringSession(acc['session']), acc['api_id'], acc['api_hash'], receive_updates=False)
    await c.start(); account_clients[aid] = c; return c
async def disconnect_client(aid):
    c = account_clients.pop(aid, None)
    if c:
        try: await c.disconnect()
        except: pass
async def get_groups(client, retry=3):
    for _ in range(retry):
        try:
            dl = await client(GetDialogsRequest(offset_date=None, offset_id=0, offset_peer=InputPeerEmpty(), limit=200, hash=0))
            gs = []
            for d in dl.dialogs:
                try:
                    e = await client.get_entity(d.peer)
                    if hasattr(e, 'title'): gs.append(e)
                except: pass
            if gs: return gs
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"groups: {e}"); await asyncio.sleep(3)
    return []
async def is_account_restricted(client):
    try:
        me = await client.get_me()
        if me is None: return True, "deleted"
        return False, None
    except (UserRestrictedError,UserDeactivatedError,UserDeactivatedBanError,AuthKeyUnregisteredError) as e:
        return True, str(e)
    except: return False, None
async def get_reply_target(client, group):
    try:
        async for m in client.iter_messages(group, limit=10):
            if m.from_id and m.sender and not getattr(m.sender,'bot',False): return m
    except: pass
    return None
async def notify_user(uid, t):
    try:
        b = Application.builder().token(BOT_TOKEN).build()
        await b.bot.send_message(chat_id=uid, text=t, parse_mode='Markdown')
    except: pass
async def join_link(client, link):
    link = link.strip().replace('http://','https://')
    if not link: raise ValueError("empty")
    if 't.me/+' in link or 'joinchat' in link:
        m = re.search(r'(?:t\.me/\+|joinchat/)([A-Za-z0-9_-]+)', link)
        if not m: raise ValueError("bad invite")
        await client(functions.messages.ImportChatInviteRequest(m.group(1)))
    else:
        m = re.search(r'(?:t\.me/|telegram\.me/|@)([A-Za-z0-9_]+)', link)
        await client(functions.channels.JoinChannelRequest(m.group(1) if m else link.lstrip('@')))
async def apply_profile(acc, name, photo, bio, channels, bot=None):
    r = []; aid = acc['id']; client = await get_client(acc)
    if not client.is_user_authorized(): return ["❌ Session is dead!"]
    if name:
        try: await client(UpdateProfileRequest(first_name=name)); r.append("✅ Name"); persist_rename(aid, name)
        except Exception as e: r.append(f"❌ Name fail: {str(e)[:40]}")
        await asyncio.sleep(1)
    if bio:
        try: await client(UpdateProfileRequest(about=bio)); r.append("✅ Bio")
        except Exception as e: r.append(f"❌ Bio fail: {str(e)[:40]}")
        await asyncio.sleep(1)
    if photo:
        p = None
        try:
            tf = await bot.get_file(photo); p = f"prof_{aid}.jpg"; await tf.download_to_drive(custom_path=p)
            with open(p,'rb') as fh: up = await client.upload_file(fh)
            await client(UploadProfilePhotoRequest(file=up)); r.append("✅ Photo")
        except Exception as e: r.append(f"❌ Photo fail: {str(e)[:40]}")
        finally:
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass
        await asyncio.sleep(1)
    for lk in channels:
        try: await join_link(client, lk); r.append(f"✅ {lk}")
        except Exception as e: r.append(f"❌ {lk} fail: {str(e)[:30]}")
        await asyncio.sleep(0.5)
    return r

async def run_account_messaging(acc, owner):
    aid = acc['id']; stop_flags[aid] = False
    account_stats.setdefault(aid, {'sent':0,'running':False,'failed_channels':[]})
    account_stats[aid]['running'] = True
    try:
        client = await get_client(acc); me = await client.get_me()
        if getattr(me,'first_name',None): persist_rename(aid, me.first_name)
        if not client.is_user_authorized():
            await notify_user(owner, f"🚨 *SESSION DEAD*\n{get_display_name(acc)}"); stop_account(aid); return
        res, reason = await is_account_restricted(client)
        if res: await notify_user(owner, f"🚨 *RESTRICTED*\n{get_display_name(acc)}"); stop_account(aid); return
        groups = await get_groups(client)
        if not groups:
            await notify_user(owner, f"⚠️ {get_display_name(acc)} - no groups"); account_stats[aid]['running'] = False; return
        cycle = 0; failed = set()
        while not stop_flags.get(aid, False):
            if not is_owner(owner) and not is_valid_admin(owner):
                stop_account(aid); return
            mn, mx, cyc = speed_for(owner)
            random.shuffle(groups)
            for g in groups:
                if stop_flags.get(aid, False): break
                if g.id in failed: continue
                try:
                    msg = get_special_msg(aid) or get_random_message_for(owner)
                    rt = await get_reply_target(client, g)
                    if rt: await client.send_message(g, msg, reply_to=rt.id)
                    else: await client.send_message(g, msg)
                    account_stats[aid]['sent'] += 1
                except FloodWaitError as e:
                    for i in range(min(e.seconds, 60)):
                        if stop_flags.get(aid): break
                        await asyncio.sleep(1)
                    if e.seconds > 60: await asyncio.sleep(e.seconds - 60)
                except (errors.UserBannedInChannelError, errors.ChatWriteForbiddenError, errors.ChatAdminRequiredError):
                    failed.add(g.id)
                except errors.RPCError as e:
                    if any(x in str(e).lower() for x in ['ban','restrict','forbidden','write','permission']): failed.add(g.id)
                except Exception as e:
                    if any(x in str(e).lower() for x in ['ban','restrict','forbidden','admin',"can't write"]): failed.add(g.id)
                await asyncio.sleep(random.randint(mn, mx))
            res, reason = await is_account_restricted(client)
            if res: await notify_user(owner, f"🚨 *RESTRICTED*\n{get_display_name(acc)}"); stop_account(aid); return
            if stop_flags.get(aid): break
            failed = set(); cycle += 1
            for i in range(cyc):
                if stop_flags.get(aid): break
                await asyncio.sleep(1)
            if cycle % 15 == 0:
                try:
                    await disconnect_client(aid); await asyncio.sleep(3)
                    if not stop_flags.get(aid):
                        client = await get_client(acc); groups = await get_groups(client)
                        me = await client.get_me()
                        if getattr(me,'first_name',None): persist_rename(aid, me.first_name)
                except Exception as e: logger.error(f"reconnect:{e}")
    except asyncio.CancelledError: pass
    except Exception as e:
        logger.error(f"fatal:{e}")
        await notify_user(owner, f"❌ Fatal: `{str(e)[:150]}`")
    finally:
        await disconnect_client(aid); account_stats[aid]['running'] = False; stop_flags[aid] = True

def stop_account(aid):
    stop_flags[aid] = True
    if aid in running_tasks and not running_tasks[aid].done():
        running_tasks[aid].cancel()
        try: del running_tasks[aid]
        except: pass
    if aid in account_stats: account_stats[aid]['running'] = False
def stop_accounts_of(u):
    for a in get_all_accounts(u): stop_account(a['id'])
def stop_all_accounts():
    for a in get_all_accounts(): stop_account(a['id'])

# ================= v7 EXPIRY CHECKER (20s warning + auto-remove) =================
async def admin_expiry_checker():
    while True:
        try:
            await asyncio.sleep(1)
            admins = load_admins(); keep = []; changed = False
            for a in admins:
                uid = a['user_id']; exp = a.get('expires_at')
                if not exp: keep.append(a); continue
                try: rem = (datetime.fromisoformat(exp) - datetime.now()).total_seconds()
                except: rem = 999999
                if rem <= 0:
                    changed = True
                    for acc in get_all_accounts(uid):
                        if account_stats.get(acc['id'], {}).get('running', False): stop_account(acc['id'])
                        await disconnect_client(acc['id'])
                    try: await notify_user(uid, f"⛔ *Plan expired*\n\n{EXPIRED_MSG}")
                    except: pass
                    warned_users.discard(uid)
                else:
                    keep.append(a)
                    if rem <= WARN_BEFORE_SEC and uid != OWNER_ID and uid not in warned_users:
                        warned_users.add(uid)
                        try: await notify_user(uid, f"⏳ Your plan expires in {int(rem)} seconds!\n\n{EXPIRED_MSG}")
                        except: pass
            if changed: save_admins(keep)
            valid = {OWNER_ID} | {a['user_id'] for a in keep if not a.get('expires_at') or (datetime.fromisoformat(a['expires_at']) > datetime.now() if a.get('expires_at') else True)}
            for acc in get_all_accounts():
                oid = acc.get('owner_id', OWNER_ID)
                if oid not in valid and account_stats.get(acc['id'], {}).get('running', False):
                    stop_account(acc['id']); await disconnect_client(acc['id'])
        except Exception as e:
            logger.error(f"expiry:{e}"); await asyncio.sleep(5)

async def test_session_only(ss):
    c = None
    try:
        if not API_ID_1 or not API_HASH_1: return False, "API missing", None, None
        c = TelegramClient(StringSession(ss), API_ID_1, API_HASH_1, receive_updates=False)
        await c.start(); me = await c.get_me()
        return True, me.first_name, me.id, c.session.save()
    except Exception as e: return False, str(e), None, None
    finally:
        if c:
            try: await c.disconnect()
            except: pass

def main_menu_keyboard(u):
    if is_owner(u):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Start All", callback_data='start_all'),
             InlineKeyboardButton("⏹️ Stop All", callback_data='stop_all')],
            [InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
            [InlineKeyboardButton("🔑 Session Login", callback_data='add_account')],
            [InlineKeyboardButton("📱 Phone Login", callback_data='phone_login')],
            [InlineKeyboardButton("🗑️ Delete Account", callback_data='delete_account')],
            [InlineKeyboardButton("🎨 Profile Setup", callback_data='profile_setup')],
            [InlineKeyboardButton("👑 Admin Panel", callback_data='admin_panel')]])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start All", callback_data='start_all'),
         InlineKeyboardButton("⏹️ Stop All", callback_data='stop_all')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
        [InlineKeyboardButton("🔑 Session Login", callback_data='add_account')],
        [InlineKeyboardButton("📱 Phone Login", callback_data='phone_login')],
        [InlineKeyboardButton("🗑️ Delete Account", callback_data='delete_account')],
        [InlineKeyboardButton("🎨 Profile Setup", callback_data='profile_setup')]])

def main_menu_text(u):
    accs = get_all_accounts(u)
    run = sum(1 for a in accs if account_stats.get(a['id'],{}).get('running',False))
    sent = sum(account_stats.get(a['id'],{}).get('sent',0) for a in accs)
    mn, mx, cyc = speed_for(u)
    role = "👑 Owner" if is_owner(u) else "👤 Admin"
    extra = ""
    if not is_owner(u):
        a = get_admin(u); exp = f"\n⏳ Time: {remaining_time_str(a.get('expires_at') if a else None)}"
        cap = admin_max_accounts(u); cur = owner_acc_count(u)
        lim = f"\n🔢 Accounts: {cur}" if cap is None else f"\n🔢 Accounts: {cur}/{cap}"
        extra = exp + lim
    return (f"✨ *Bot v7.0 FINAL* ✨\n{role}{extra}\n\n"
            f"📊 Accounts: {len(accs)} (Running: {run})\n"
            f"⚡ Speed: {mn}-{mx}s | 🔄 Cycle: {cyc}s\n📨 Sent: {sent}")

async def start_command(u, c):
    uid = u.effective_user.id
    eu = u.effective_user
    record_user_info(uid, eu.first_name, eu.last_name, eu.username)
    # ---- v7: referral deep link ----
    args = u.message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith('ref_'):
        rid = find_referrer_by_code(args[1][4:])
        if rid and rid != uid and get_referrer_of(uid) is None:
            set_referred(uid, rid)
            try:
                await c.bot.send_message(rid, f"👥 New referral joined: {eu.first_name} (ID: {uid})")
            except: pass
    if is_blocked(uid):
        await u.message.reply_text("🚫 You are blocked. Contact admin 👉 @G18GamerBacko"); return
    if is_owner(uid) or is_valid_admin(uid):
        refresh_account_stats(uid); preload_display_names(get_all_accounts(uid))
        await u.message.reply_text(main_menu_text(uid), parse_mode='Markdown', reply_markup=main_menu_keyboard(uid))
        return
    # ---- v7: expired / normal user panel ----
    await u.message.reply_text(expired_panel_text(), parse_mode='Markdown', reply_markup=expired_panel_keyboard())

async def apply_admin_time(target, op, nd, q=None, text_ui=None):
    now = datetime.now()
    admins = load_admins(); a = get_admin(target)
    if a is None:
        a = {'user_id':target,'expires_at':None if nd is None else nd.isoformat(),
             'added_at':now.isoformat(),'updated_at':now.isoformat(),'max_accounts':DEFAULT_ADMIN_LIMIT}
        admins.append(a); save_admins(admins)
        chg = remaining_time_str(a['expires_at'])
        resp = f"✅ Admin added: {admin_label(target)}\n⏳ Time: {chg}"
    else:
        if nd is None:
            if op == '-': a['expires_at'] = now.isoformat(); chg = "expired now"
            else: a['expires_at'] = None; chg = "♾️ Permanent"
        else:
            cur = None
            try: cur = datetime.fromisoformat(a['expires_at']) if a.get('expires_at') else None
            except: cur = None
            rem = (cur - now) if (cur and cur > now) else timedelta(0)
            dl = nd - now
            if op == '=': ne = nd
            elif op == '-':
                ne = now + (rem - dl)
                if ne < now: ne = now
            else: ne = now + dl + rem
            a['expires_at'] = ne.isoformat(); chg = remaining_time_str(a['expires_at'])
        a['updated_at'] = now.isoformat()
        replace_admin(target, a)
        resp = f"✅ Admin updated: {admin_label(target)}\n⏳ Time: {chg}"
    if text_ui is not None:
        try: await text_ui.reply_text(resp, parse_mode='Markdown', reply_markup=BACK_KB)
        except: pass
    elif q is not None:
        try: await q.edit_message_text(resp, parse_mode='Markdown', reply_markup=BACK_KB)
        except: pass
    return resp

async def do_broadcast(reply_target, bot, uid, caption="", media_file=None, media_type="text", only_user_id=None):
    if not is_owner(uid): return
    targets = [only_user_id] if only_user_id is not None else broadcast_targets()
    if not targets:
        try: await reply_target.reply_text("❌ No target available", reply_markup=BACK_KB)
        except: pass
        return
    ok = 0
    for t in targets:
        try:
            if media_type == 'photo': await bot.send_photo(chat_id=t, photo=media_file, caption=caption)
            elif media_type == 'video': await bot.send_video(chat_id=t, video=media_file, caption=caption)
            elif media_type == 'animation': await bot.send_animation(chat_id=t, animation=media_file, caption=caption)
            else: await bot.send_message(chat_id=t, text=caption)
            ok += 1
        except Exception as e: logger.error(f"bc:{e}")
    try:
        who = "single user" if only_user_id is not None else "all admins"
        await reply_target.reply_text(f"📢 Broadcast sent to {ok} ({who})", reply_markup=BACK_KB)
    except: pass

async def button_click(u, c):
    global MIN_INTERVAL, MAX_INTERVAL, CYCLE_WAIT, SHOW_START_TO_OTHERS
    q = u.callback_query; await q.answer(); uid = q.from_user.id
    frm = q.from_user
    record_user_info(uid, frm.first_name, frm.last_name, frm.username)
    d = q.data

    # ---- v7: free callbacks available to everyone (incl. expired users) ----
    ALLOWED_FREE_PREFIXES = ('buy_', 'paid_', 'refbuy_', 'back_start', 'ref_menu', 'ref_buy_menu')
    ALLOWED_FREE_EXACT = ('payok_', 'payno_', 'payblock_')  # owner handled inside
    is_free = any(d.startswith(x) for x in ALLOWED_FREE_PREFIXES) or any(d.startswith(x) for x in ALLOWED_FREE_EXACT)
    if not (is_owner(uid) or is_valid_admin(uid)) and not is_free:
        if SHOW_START_TO_OTHERS: await q.edit_message_text("⛔ Access denied / expired.")
        else: await q.edit_message_text(" ")
        return

    # ================= v7 BUY FLOW =================
    if d.startswith('buy_'):
        pid = d.replace('buy_', '')
        plan = next((p for p in load_plans() if p['plan_id'] == pid), None)
        if not plan:
            await q.edit_message_text("❌ Plan unavailable", reply_markup=expired_panel_keyboard()); return
        kb = [[InlineKeyboardButton("✅ I Have Paid", callback_data=f'paid_{pid}')]]
        if get_balance(uid) >= float(plan['price']):
            kb.append([InlineKeyboardButton(f"💰 Pay with balance (₹{plan['price']})", callback_data=f'refbuy_{pid}')])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='back_start')])
        cap = f"\n\n💎 {plan['name']}\n💸 Price: ₹{plan['price']}\n⏳ Duration: {plan['days']} days"
        qr = load_qr()
        try: await q.message.delete()
        except: pass
        if qr.get('photo'):
            await c.bot.send_photo(uid, photo=qr['photo'], caption="💳 Pay via this QR" + cap, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        else:
            await c.bot.send_message(uid, "💳 Pay to admin (QR not set yet)" + cap, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'back_start':
        try: await q.message.delete()
        except: pass
        await c.bot.send_message(uid, expired_panel_text(), parse_mode='Markdown', reply_markup=expired_panel_keyboard())
    elif d.startswith('paid_'):
        pid = d.replace('paid_', '')
        plan = next((p for p in load_plans() if p['plan_id'] == pid), None)
        if not plan: return
        c.user_data['awaiting'] = 'pay_screenshot'
        c.user_data['pay_plan'] = pid
        try: await q.message.delete()
        except: pass
        await c.bot.send_message(uid, "📸 Please send your payment screenshot.", reply_markup=BACK_KB)
    elif d.startswith('refbuy_'):
        pid = d.replace('refbuy_', '')
        plan = next((p for p in load_plans() if p['plan_id'] == pid), None)
        if not plan or get_balance(uid) < float(plan['price']):
            await q.edit_message_text("❌ Insufficient balance", reply_markup=expired_panel_keyboard()); return
        add_balance(uid, -float(plan['price']))
        await activate_plan(uid, int(plan['days']), plan['name'])
        ref = get_referrer_of(uid)
        if ref:
            comm = round(float(plan['price']) * 0.20, 2)
            add_balance(ref, comm)
            r = load_json(REFS_FILE, {}); r[str(ref)]['earnings'] = r[str(ref)].get('earnings', 0) + comm; save_json(REFS_FILE, r)
            nm = load_names().get(str(uid), {}).get('name', str(uid))
            try: await c.bot.send_message(ref, f"💰 You referred {nm}.\nThey bought '{plan['name']}' for ₹{plan['price']}.\n✅ 20% (₹{comm}) added to your balance.")
            except: pass
        try: await q.edit_message_text("✅ Plan activated with balance!", reply_markup=expired_panel_keyboard())
        except: pass
    elif d == 'ref_menu':
        code = get_ref_code(uid)
        me = await c.bot.get_me()
        r = load_json(REFS_FILE, {}).get(str(uid), {})
        await q.edit_message_text(
            f"👥 *Referral System*\n\n🔗 Your link:\n`https://t.me/{me.username}?start=ref_{code}`\n\n"
            f"💰 Balance: ₹{get_balance(uid)}\n👥 Referred: {len(r.get('referred', []))}\n📈 Earnings: ₹{r.get('earnings', 0)}\n\n"
            f"_When someone you referred buys a plan, you get 20% of the price in your balance._",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='back_start')]]))
    elif d == 'ref_buy_menu':
        kb = [[InlineKeyboardButton(f"{p['name']} — ₹{p['price']} ({p['days']}d)", callback_data=f"buy_{p['plan_id']}")] for p in load_plans()]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='back_start')])
        await q.edit_message_text(f"💰 Your balance: ₹{get_balance(uid)}\nChoose a plan:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    # ---- v7 owner payment review ----
    elif d.startswith('payok_'):
        if not is_owner(uid): return
        _, buyer_s, pid = d.split('_', 2)
        buyer = int(buyer_s)
        plan = next((p for p in load_plans() if p['plan_id'] == pid), None)
        if not plan:
            await q.edit_message_text("❌ Plan gone"); return
        await activate_plan(buyer, int(plan['days']), plan['name'])
        comm_msg = ""
        ref = get_referrer_of(buyer)
        if ref:
            comm = round(float(plan['price']) * 0.20, 2)
            add_balance(ref, comm)
            r = load_json(REFS_FILE, {}); r[str(ref)]['earnings'] = r[str(ref)].get('earnings', 0) + comm; save_json(REFS_FILE, r)
            nm = load_names().get(str(buyer), {}).get('name', str(buyer))
            try: await c.bot.send_message(ref, f"💰 You referred {nm}.\nThey bought '{plan['name']}' for ₹{plan['price']}.\n✅ 20% (₹{comm}) added to your balance.")
            except: pass
            comm_msg = f"\n👥 Referral commission ₹{comm} → ID {ref}"
        try: await q.edit_message_text(f"✅ Accepted payment of {buyer} ({plan['name']}){comm_msg}")
        except: pass
    elif d.startswith('payno_'):
        if not is_owner(uid): return
        buyer = int(d.split('_')[1])
        try: await c.bot.send_message(buyer, "❌ Your payment was rejected. Contact admin 👉 @G18GamerBacko")
        except: pass
        await q.edit_message_text("❌ Rejected & user notified")
    elif d.startswith('payblock_'):
        if not is_owner(uid): return
        buyer = int(d.split('_')[1])
        try: await c.bot.send_message(buyer, "🚫 You have been blocked for fake payment.")
        except: pass
        bl = load_json(BLOCKED_FILE, [])
        if buyer not in bl: bl.append(buyer); save_json(BLOCKED_FILE, bl)
        await q.edit_message_text("🚫 User blocked")

    elif d == 'start_all':
        p = []
        for a in get_all_accounts(uid):
            if account_stats.get(a['id'],{}).get('running',False): p.append(f"✅ Already running: {get_display_name(a)}")
            else:
                stop_flags[a['id']] = False
                running_tasks[a['id']] = asyncio.create_task(run_account_messaging(a, uid))
                p.append(f"▶️ Started: {get_display_name(a)}")
        await q.edit_message_text("\n".join(p) if p else "❌ No accounts", reply_markup=BACK_KB)
    elif d == 'stop_all':
        p = []
        for a in get_all_accounts(uid):
            if account_stats.get(a['id'],{}).get('running',False): stop_account(a['id']); p.append(f"⏹️ Stopping: {get_display_name(a)}")
            else: p.append(f"⏸️ Stopped: {get_display_name(a)}")
        await q.edit_message_text("\n".join(p) if p else "✅ Nothing running", reply_markup=BACK_KB)
    elif d == 'status':
        accs = get_all_accounts(uid); txt = "📊 *Status*\n\n"
        for i, a in enumerate(accs, 1):
            st = '🟢 RUNNING' if account_stats.get(a['id'],{}).get('running',False) else '🔴 STOPPED'
            txt += f"#{i} · {get_display_name(a)}\n ↳ {st} | Sent: {account_stats.get(a['id'],{}).get('sent',0)}\n"
        if not accs: txt += "_None_\n"
        txt += f"\n📨 Total: {sum(account_stats.get(a['id'],{}).get('sent',0) for a in accs)}"
        await q.edit_message_text(txt, parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'settings':
        mn, mx, cyc = speed_for(uid)
        kb = [[InlineKeyboardButton("📊 Status", callback_data='status')],
              [InlineKeyboardButton("📝 Messages", callback_data='message_list'),
               InlineKeyboardButton("⏱️ Speed", callback_data='edit_speed')],
              [InlineKeyboardButton("📌 Special Msg", callback_data='special_msg_menu')],
              [InlineKeyboardButton("🔙 Back", callback_data='back_main')]]
        await q.edit_message_text(f"⚙️ *Settings*\n⚡ Speed: {mn}-{mx}s | 🔄 Cycle: {cyc}s", parse_mode='Markdown',
                                  reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'message_list':
        m = load_messages_for(uid); txt = f"📝 *Your Messages* ({len(m)}):\n" + "".join(f"`{x[:40]}`\n\n" for x in m[:10])
        kb = [[InlineKeyboardButton("➕ Add", callback_data='add_message'), InlineKeyboardButton("🗑️ Delete", callback_data='delete_message_menu')],
              [InlineKeyboardButton("🔄 Reset", callback_data='reset_messages')],
              [InlineKeyboardButton("🔙 Back", callback_data='settings')]]
        await q.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'edit_speed':
        mn, mx, cyc = speed_for(uid)
        kb = [[InlineKeyboardButton(f"⏱️ Min {mn}s", callback_data='set_min'), InlineKeyboardButton(f"⏱️ Max {mx}s", callback_data='set_max')],
              [InlineKeyboardButton(f"🔄 Cycle {cyc}s", callback_data='set_cycle')],
              [InlineKeyboardButton("🔙 Back", callback_data='settings')]]
        await q.edit_message_text("⏱️ *Speed Settings*\n(For your own accounts)", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'add_message': c.user_data['awaiting'] = 'add_message'; await q.edit_message_text("✏️ Send the new message text:", reply_markup=BACK_KB)
    elif d == 'delete_message_menu':
        m = load_messages_for(uid)
        if not m: await q.edit_message_text("❌ No messages yet", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"🗑️ {i+1}. {x[:20]}", callback_data=f'del_msg_{i}')] for i,x in enumerate(m)]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='message_list')])
        await q.edit_message_text("Which one to delete?", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('del_msg_'):
        m = load_messages_for(uid); i = int(d.replace('del_msg_',''))
        if 0 <= i < len(m): m.pop(i); save_messages_for(uid, m)
        await q.edit_message_text("🗑️ Deleted", reply_markup=BACK_KB)
    elif d == 'reset_messages': save_messages_for(uid, [MESSAGE]); await q.edit_message_text("🔄 Reset done", reply_markup=BACK_KB)
    elif d == 'set_min':
        mn, mx, cyc = speed_for(uid); c.user_data['awaiting'] = 'set_min'
        await q.edit_message_text(f"⏱️ Enter Min seconds (1 - {mx-1}):", reply_markup=BACK_KB)
    elif d == 'set_max':
        mn, mx, cyc = speed_for(uid); c.user_data['awaiting'] = 'set_max'
        await q.edit_message_text(f"⏱️ Enter Max seconds (> {mn}):", reply_markup=BACK_KB)
    elif d == 'set_cycle': c.user_data['awaiting'] = 'set_cycle'; await q.edit_message_text("🔄 Enter cycle seconds (5+):", reply_markup=BACK_KB)
    elif d == 'special_msg_menu':
        accs = get_all_accounts(uid)
        if not accs: await q.edit_message_text("❌ No accounts", reply_markup=BACK_KB); return
        kb = []
        for i, a in enumerate(accs, 1):
            sm = get_special_msg(a['id'])
            mark = "📌" if sm else "▫️"
            kb.append([InlineKeyboardButton(f"{mark} #{i} · {get_display_name(a)[:16]}",
                                            callback_data=f'spec_show_{a["id"]}')])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='settings')])
        await q.edit_message_text("📌 *Special Message*\nSelect an account:", parse_mode='Markdown',
                                  reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('spec_show_'):
        aid = d.replace('spec_show_', '')
        if aid not in [a['id'] for a in get_all_accounts(uid)]:
            await q.edit_message_text("⛔ Not your account", reply_markup=BACK_KB); return
        sm = get_special_msg(aid)
        cur = f"📝 Current:\n`{sm[:300]}`" if sm else "_No special message (normal random)_"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Set / Change", callback_data=f'spec_set_{aid}')],
            [InlineKeyboardButton("🗑️ Clear", callback_data=f'spec_clear_{aid}')],
            [InlineKeyboardButton("🔙 Back", callback_data='special_msg_menu')]])
        await q.edit_message_text(f"📌 *{get_display_name_by_id(aid)}*\n{cur}\n\n_এই id থেকে শুধু এই special message-ই spam হবে, বাকি accounts স্বাভাবিক চলবে।_",
                                  parse_mode='Markdown', reply_markup=kb)
    elif d.startswith('spec_set_'):
        aid = d.replace('spec_set_', '')
        if aid not in [a['id'] for a in get_all_accounts(uid)]:
            await q.edit_message_text("⛔ Not your account", reply_markup=BACK_KB); return
        c.user_data['awaiting'] = 'spec_set_msg'; c.user_data['spec_aid'] = aid
        await q.edit_message_text("✏️ Send the SPECIAL message text now.\n(শুধু এই মেসেজটাই এই id থেকে spam হবে)\n`/cancel` = বাতিল",
                                  parse_mode='Markdown', reply_markup=BACK_KB)
    elif d.startswith('spec_clear_'):
        aid = d.replace('spec_clear_', '')
        if aid not in [a['id'] for a in get_all_accounts(uid)]:
            await q.edit_message_text("⛔ Not your account", reply_markup=BACK_KB); return
        set_special_msg(aid, "")
        await q.edit_message_text("🗑️ Special message removed — এই id আবার সাধারণ random spam করবে।", reply_markup=BACK_KB)
    elif d == 'profile_setup':
        accs = get_all_accounts(uid); cfg = get_default_profile(); nm = cfg.get('names',[]); ph = cfg.get('photos',[])
        if not accs: await q.edit_message_text("❌ No accounts", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"⚙️ Profile Config (Names:{len(nm)}|Logos:{len(ph)})", callback_data='profdefault')],
              [InlineKeyboardButton("⚡ Apply to ALL accounts", callback_data='profapply_all')],
              [InlineKeyboardButton("🔙 Back", callback_data='back_main')]]
        await q.edit_message_text(f"🎨 *Profile Setup*\nAccounts: {len(accs)}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'profdefault':
        cfg = get_default_profile(); nm = cfg.get('names',[]); ph = cfg.get('photos',[]); ch = cfg.get('channels',[])
        txt = f"⚙️ *Profile Config*\n📝 Names ({len(nm)})\n🖼️ Logos: {len(ph)} | 📄 Bio: `{cfg.get('bio','-')}`\n📢 Channels ({len(ch)})\n" + "".join(f" {x}\n" for x in ch[:10])
        kb = [[InlineKeyboardButton("➕ Add Name", callback_data='def_add_name'), InlineKeyboardButton("➖ Del Name", callback_data='def_del_name')],
              [InlineKeyboardButton("🖼️ Add Logo", callback_data='def_add_photo'), InlineKeyboardButton("🗑️ Del Logo", callback_data='def_del_photo')],
              [InlineKeyboardButton("📄 Set Bio", callback_data='def_bio')],
              [InlineKeyboardButton("📢 Channels", callback_data='def_chan')],
              [InlineKeyboardButton("🔄 Reset", callback_data='def_reset')],
              [InlineKeyboardButton("🔙 Back", callback_data='profile_setup')]]
        await q.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'def_add_name': c.user_data['awaiting'] = 'def_add_name'; await q.edit_message_text("📝 Send names, one per line:", reply_markup=BACK_KB)
    elif d == 'def_del_name':
        nm = get_default_profile().get('names',[])
        if not nm: await q.edit_message_text("❌ No names", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"➖ {x[:25]}", callback_data=f'def_delname_{i}')] for i,x in enumerate(nm)]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='profdefault')])
        await q.edit_message_text("Which?", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('def_delname_'):
        cfg = get_default_profile(); nm = cfg.get('names',[]); i = int(d.replace('def_delname_',''))
        if 0 <= i < len(nm): nm.pop(i); cfg['names'] = nm; save_default_profile(cfg)
        await q.edit_message_text("🗑️ Deleted", reply_markup=BACK_KB)
    elif d == 'def_add_photo': c.user_data['awaiting'] = 'def_add_photo'; await q.edit_message_text("🖼️ Send a photo:", reply_markup=BACK_KB)
    elif d == 'def_del_photo':
        ph = get_default_profile().get('photos',[])
        if not ph: await q.edit_message_text("❌ No logos", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"🗑️ Logo #{i+1}", callback_data=f'def_delphoto_{i}')] for i in range(len(ph))]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='profdefault')])
        await q.edit_message_text("Which?", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('def_delphoto_'):
        cfg = get_default_profile(); ph = cfg.get('photos',[]); i = int(d.replace('def_delphoto_',''))
        if 0 <= i < len(ph): ph.pop(i); cfg['photos'] = ph; save_default_profile(cfg)
        await q.edit_message_text("🗑️ Deleted", reply_markup=BACK_KB)
    elif d == 'def_bio': c.user_data['awaiting'] = 'def_bio'; await q.edit_message_text("📄 Send bio text:", reply_markup=BACK_KB)
    elif d == 'def_chan': c.user_data['awaiting'] = 'def_chan'; await q.edit_message_text("📢 Send channel links (line wise):", reply_markup=BACK_KB)
    elif d == 'def_reset': save_default_profile({}); await q.edit_message_text("🔄 Reset done", reply_markup=BACK_KB)
    elif d == 'profapply_all':
        accs = get_all_accounts(uid); cfg = get_default_profile()
        nm = cfg.get('names',[]); ph = cfg.get('photos',[]); bio = cfg.get('bio',''); ch = cfg.get('channels',[])
        if not accs or (not nm and not ph and not bio and not ch): await q.edit_message_text("❌ Add config first!", reply_markup=BACK_KB); return
        total = len(accs); prog = {'done':0,'lines':{}}
        sm = await q.edit_message_text("⚡ Applying 0%")
        async def one(i, acc):
            try:
                rr = await apply_profile(acc, nm[i%len(nm)] if nm else '', ph[i%len(ph)] if ph else None, bio, ch, bot=c.bot)
                ok = sum(1 for x in rr if x.startswith('✅'))
                prog['lines'][i] = f"#{i+1} · {get_display_name(acc)[:15]}: ok {ok}"
            except Exception as e: prog['lines'][i] = f"#{i+1}: fail {str(e)[:30]}"
            prog['done'] += 1
        tasks = [asyncio.create_task(one(i,a)) for i,a in enumerate(accs)]
        while any(not t.done() for t in tasks):
            pct = int(prog['done']*100/total)
            try: await sm.edit_text(f"{'█'*(pct//10)}{'░'*(10-pct//10)} {pct}%")
            except: pass
            await asyncio.sleep(2)
        await asyncio.gather(*tasks, return_exceptions=True)
        await sm.edit_text("✅ *Done!*\n\n" + "\n".join(prog['lines'][i] for i in sorted(prog['lines'])), parse_mode='Markdown', reply_markup=BACK_KB)

    # owner-only
    elif d == 'admin_panel':
        if not is_owner(uid): return
        kb = [[InlineKeyboardButton("➕ Add / Edit Admin", callback_data='add_admin'),
               InlineKeyboardButton("📋 Admin List", callback_data='admin_list')],
              [InlineKeyboardButton("🔢 Set Account Limit", callback_data='set_admin_limit'),
               InlineKeyboardButton("💰 Plans & QR", callback_data='plans_menu')],
              [InlineKeyboardButton(f"👻 Start-msg: {'ON' if SHOW_START_TO_OTHERS else 'OFF'}", callback_data='toggle_startmsg')],
              [InlineKeyboardButton("📢 Broadcast", callback_data='broadcast_menu')],
              [InlineKeyboardButton("🔙 Back", callback_data='back_main')]]
        await q.edit_message_text("👑 *Admin Panel* ✨ _(Owner only)_", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'broadcast_menu':
        if not is_owner(uid): return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 To All Admins", callback_data='bc_all')],
            [InlineKeyboardButton("👤 To One User", callback_data='bc_one')],
            [InlineKeyboardButton("🔙 Back", callback_data='admin_panel')]])
        await q.edit_message_text("📨 *Broadcast*\nChoose target:", parse_mode='Markdown', reply_markup=kb)
    elif d == 'bc_all':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'broadcast_capture'; c.user_data.pop('bc_uid', None)
        await q.edit_message_text("📢 Now send text / photo / video — goes to all admins.\nCancel = /cancel",
                                  parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'bc_one':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'broadcast_target'
        await q.edit_message_text("👤 Send the target USER_ID (only number):\nCancel = /cancel",
                                  parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'set_admin_limit':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'admin_limit'
        await q.edit_message_text("🔢 Format: `USER_ID NUMBER`\n(0 = unlimited)", parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'add_admin':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'add_admin'
        await q.edit_message_text(
            "➕ *Add / Edit Admin*\n\nFormat:\n`USER_ID [+|-|=]TIME`\n\n"
            "TIME mixes units — seconds / minutes / hours / days / weeks:\n"
            "🔸 `111 +2d` → add 2 days\n"
            "🔸 `111 +2d 5h 30m` → add 2d+5h+30m\n"
            "🔸 `111 -1d 2h` → subtract\n"
            "🔸 `111 +1w` → add 1 week\n"
            "🔸 `111 =45s` → exactly 45 seconds\n"
            "🔸 `111 =perm` → permanent\n"
            "🔸 `111 -10s` → reduce\n\nName apne aap ID ke saath dikhega.",
            parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'toggle_startmsg':
        if not is_owner(uid): return
        SHOW_START_TO_OTHERS = not SHOW_START_TO_OTHERS; save_data()
        await q.edit_message_text(f"👻 Show msg to non-admins on /start: {'ON' if SHOW_START_TO_OTHERS else 'OFF'}", reply_markup=BACK_KB)
    elif d == 'admin_list':
        if not is_owner(uid): return
        admins = load_admins()
        if not admins: await q.edit_message_text("❌ No admins yet", reply_markup=BACK_KB); return
        txt = "📋 *Admins*\n\n"; kb = []
        for a in admins:
            accs = get_all_accounts(a['user_id'])
            cap = a.get('max_accounts'); cap_str = f"🔢 Accounts: {len(accs)}" if not cap else f"🔢 Accounts: {len(accs)}/{cap}"
            txt += f"👤 {admin_label(a['user_id'])}\n ⏳ {remaining_time_str(a.get('expires_at'))}\n {cap_str}\n\n"
            kb.append([InlineKeyboardButton(f"🕐 Edit · {get_names_short(a['user_id'])} ({a['user_id']})", callback_data=f'admin_edit_{a["user_id"]}'),
                       InlineKeyboardButton(f"🗑️", callback_data=f'del_admin_{a["user_id"]}')])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='admin_panel')])
        await q.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'plans_menu':
        if not is_owner(uid): return
        plans = load_plans(); qr = load_qr()
        txt = "💰 *Plans*\n" + "".join(f"\n▫️ {p['name']} | ₹{p['price']} | {p['days']}d | 🖲 {p['btn_name']}" for p in plans)
        txt += f"\n\n🖼️ QR: {'✅ set' if qr.get('photo') else '❌ not set'}"
        kb = [[InlineKeyboardButton("➕ Add Plan", callback_data='plan_add'),
               InlineKeyboardButton("🗑️ Del Plan", callback_data='plan_del')],
              [InlineKeyboardButton("🖼️ Set QR Photo", callback_data='qr_set')],
              [InlineKeyboardButton("🔙 Back", callback_data='admin_panel')]]
        await q.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'plan_add':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'plan_add'
        await q.edit_message_text("➕ Send plan in this format:\n`Button Name | Plan Name | PRICE | DAYS`\nExample:\n`Buy 30 Days 🔥 | 30 Days Access | 150 | 30`", parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'plan_del':
        if not is_owner(uid): return
        plans = load_plans()
        if not plans: await q.edit_message_text("❌ No plans", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"🗑️ {p['name']}", callback_data=f'plan_del_{p["plan_id"]}')] for p in plans]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='plans_menu')])
        await q.edit_message_text("Which plan?", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('plan_del_'):
        if not is_owner(uid): return
        pid = d.replace('plan_del_', '')
        save_plans([p for p in load_plans() if p['plan_id'] != pid])
        await q.edit_message_text("🗑️ Deleted", reply_markup=BACK_KB)
    elif d == 'qr_set':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'qr_set'
        await q.edit_message_text("🖼️ Send the payment QR photo:", reply_markup=BACK_KB)
    elif d.startswith('admin_edit_'):
        if not is_owner(uid): return
        t = int(d.replace('admin_edit_',''))
        a = get_admin(t)
        if not a: await q.edit_message_text("❌ Not an admin", reply_markup=BACK_KB); return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕30d", callback_data=f'admop_{t}_+30'), InlineKeyboardButton("➕100d", callback_data=f'admop_{t}_+100')],
            [InlineKeyboardButton("➖10d", callback_data=f'admop_{t}_-10'), InlineKeyboardButton("➖30d", callback_data=f'admop_{t}_-30')],
            [InlineKeyboardButton("✍️ Custom Time", callback_data=f'adm_time_{t}')],
            [InlineKeyboardButton("♾️ Permanent", callback_data=f'admop_{t}_=perm'), InlineKeyboardButton("⛔ Expire", callback_data=f'admop_{t}_=0')],
            [InlineKeyboardButton("🔙 Back", callback_data='admin_list')]])
        accs = get_all_accounts(t)
        names = "\n".join(f" • {get_display_name(x)}" for x in accs[:10]) or "  _none_"
        await q.edit_message_text(f"👤 {admin_label(t)}\n⏳ {remaining_time_str(a.get('expires_at'))}\n📊 Accounts:\n{names}",
                                  parse_mode='Markdown', reply_markup=kb)
    elif d.startswith('adm_time_'):
        if not is_owner(uid): return
        try: t = int(d.replace('adm_time_',''))
        except: await q.edit_message_text("❌ Parse error", reply_markup=BACK_KB); return
        c.user_data['awaiting'] = 'adm_custom_time'; c.user_data['adm_target'] = t
        await q.edit_message_text(
            "⏳ *Custom Time (Add)*\n\nSend duration — 1 second থেকে যত খুশি:\n"
            "🔹 `45s` → 45 sec\n🔹 `30m` → 30 min\n🔹 `2d 5h` → 2d 5h\n🔹 `1d` → 1 day\n🔹 `1w` → 1 week\n"
            "(`-30m` দিলে subtract)\n\nএখন লিখে পাঠান:",
            parse_mode='Markdown', reply_markup=BACK_KB)
    elif d.startswith('admop_'):
        if not is_owner(uid): return
        try:
            body = d.replace('admop_',''); t_s, op = body.rsplit('_',1); target = int(t_s)
        except Exception:
            await q.edit_message_text("❌ Parse error", reply_markup=BACK_KB); return
        now = datetime.now()
        if op == 'perm': await apply_admin_time(target, '=', None, q=q)
        elif op == '0':
            a = get_admin(target)
            if a: a['expires_at'] = now.isoformat(); a['updated_at']=now.isoformat(); replace_admin(target,a)
            await q.edit_message_text(f"⛔ Admin expired: {admin_label(target)}", reply_markup=BACK_KB)
        else:
            amt = int(op.replace('+','').replace('-','')); o = '+' if op.startswith('+') else '-'
            nd = now + timedelta(days=amt)
            await apply_admin_time(target, o, nd, q=q)
    elif d.startswith('del_admin_'):
        if not is_owner(uid): return
        tt = int(d.replace('del_admin_',''))
        lbl = admin_label(tt)
        save_admins([a for a in load_admins() if a['user_id'] != tt]); stop_accounts_of(tt)
        await q.edit_message_text(f"🗑️ Admin deleted: {lbl}\n(accounts stopped)", reply_markup=BACK_KB)
    elif d == 'phone_login':
        c.user_data['awaiting'] = 'phone_number'
        await q.edit_message_text("📱 *Phone Login*\nSend number in intl. format (add country code).\nIndia: `+91XXXXXXXXXX`",
                                  parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'add_account':
        c.user_data['awaiting'] = 'add_account'; await q.edit_message_text("🔑 *Session Login*\nPaste your session string:", parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'delete_account':
        accs = get_all_accounts(uid)
        if not accs: await q.edit_message_text("❌ No accounts", reply_markup=BACK_KB); return
        kb = []
        for i, a in enumerate(accs, 1):
            ti = {'env':'💚','dynamic':'💙','phone_auth':'📱'}.get(a.get('type',''),'❓')
            kb.append([InlineKeyboardButton(f"{ti} #{i} · {get_display_name(a)[:20]}", callback_data=f'del_acc_{a["id"]}')])
        kb += [[InlineKeyboardButton("🗑️ Delete ALL", callback_data='del_all_accounts'), InlineKeyboardButton("🔙 Back", callback_data='back_main')]]
        await q.edit_message_text("Delete which?", reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'del_all_accounts':
        dd = [a for a in get_all_accounts(uid) if a.get('type') != 'env']
        kb = [[InlineKeyboardButton("☠️ YES Delete All", callback_data='del_all_confirm'), InlineKeyboardButton("Cancel", callback_data='delete_account')]]
        await q.edit_message_text(f"⚠️ Delete {len(dd)} accounts?", reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'del_all_confirm':
        n = 0
        for a in get_all_accounts(uid):
            if a.get('type') == 'env': continue
            stop_account(a['id']); remove_account_by_id(a['id']); await disconnect_client(a['id'])
            set_special_msg(a['id'], ""); n += 1
        await q.edit_message_text(f"🗑️ Deleted {n}", reply_markup=BACK_KB)
    elif d.startswith('del_acc_'):
        acc_id = d.replace('del_acc_',''); t = None
        for a in get_all_accounts(uid):
            if a['id'] == acc_id: t = a; break
        if not t: await q.edit_message_text("⛔ invalid", reply_markup=BACK_KB); return
        nm = get_display_name(t)
        if account_stats.get(acc_id,{}).get('running',False): stop_account(acc_id); await asyncio.sleep(1)
        remove_account_by_id(acc_id); await disconnect_client(acc_id)
        set_special_msg(acc_id, "")
        for dd in (account_stats, stop_flags, running_tasks, display_names): dd.pop(acc_id, None)
        await q.edit_message_text(f"🗑️ Deleted: {nm}", reply_markup=BACK_KB)
    elif d == 'back_main':
        c.user_data['awaiting'] = None; c.user_data.pop('login_id', None)
        refresh_account_stats(uid); preload_display_names(get_all_accounts(uid))
        await q.edit_message_text(main_menu_text(uid), parse_mode='Markdown', reply_markup=main_menu_keyboard(uid))

async def handle_photo(u, c):
    uid = u.effective_user.id
    eu = u.effective_user
    record_user_info(uid, eu.first_name, eu.last_name, eu.username)

    # ---- v7: payment screenshot (works for ANY user, incl. expired) ----
    if c.user_data.get('awaiting') == 'pay_screenshot' and u.message.photo:
        pid = c.user_data.pop('pay_plan', None); c.user_data['awaiting'] = None
        if not pid:
            await u.message.reply_text("❌ Session reset. Choose a plan again.", reply_markup=expired_panel_keyboard()); return
        plan = next((p for p in load_plans() if p['plan_id'] == pid), None)
        nm = load_names().get(str(uid), {}).get('name', str(uid))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Accept", callback_data=f'payok_{uid}_{pid}'),
             InlineKeyboardButton("❌ Reject", callback_data=f'payno_{uid}')],
            [InlineKeyboardButton("🚫 Block User", callback_data=f'payblock_{uid}')]])
        try:
            await c.bot.send_photo(OWNER_ID, photo=u.message.photo[-1].file_id,
                caption=f"💳 *Payment from:* {nm} (ID: {uid})\n💎 Plan: {plan['name'] if plan else pid} — ₹{plan['price'] if plan else '?'}",
                parse_mode='Markdown', reply_markup=kb)
            await u.message.reply_text("✅ Sent to admin! Please wait for confirmation.", reply_markup=expired_panel_keyboard())
        except Exception as e:
            await u.message.reply_text(f"❌ {str(e)[:100]}")
        return

    # ---- v7: QR photo set (owner) ----
    if c.user_data.get('awaiting') == 'qr_set' and is_owner(uid) and u.message.photo:
        qr = load_qr(); qr['photo'] = u.message.photo[-1].file_id; save_qr(qr)
        c.user_data['awaiting'] = None
        await u.message.reply_text("✅ QR saved!", reply_markup=BACK_KB); return

    if not (is_owner(uid) or is_valid_admin(uid)): return
    if c.user_data.get('awaiting') == 'def_add_photo':
        cfg = get_default_profile(); ph = cfg.get('photos',[]); ph.append(u.message.photo[-1].file_id)
        cfg['photos'] = ph; save_default_profile(cfg); c.user_data['awaiting'] = None
        await u.message.reply_text(f"🖼️ Logo #{len(ph)} saved", reply_markup=BACK_KB); return
    if c.user_data.get('awaiting') == 'broadcast_capture' and is_owner(uid):
        c.user_data['awaiting'] = None
        tid = c.user_data.pop('bc_uid', None)
        if u.message.video:
            await do_broadcast(u.message, c.bot, uid, u.message.caption or "", u.message.video.file_id, 'video', only_user_id=tid)
        elif u.message.photo:
            await do_broadcast(u.message, c.bot, uid, u.message.caption or "", u.message.photo[-1].file_id, 'photo', only_user_id=tid)
        elif u.message.animation:
            await do_broadcast(u.message, c.bot, uid, u.message.caption or "", u.message.animation.file_id, 'animation', only_user_id=tid)

async def handle_text(u, c):
    uid = u.effective_user.id
    eu = u.effective_user
    record_user_info(uid, eu.first_name, eu.last_name, eu.username)
    text = u.message.text.strip()
    aw = c.user_data.get('awaiting')

    # ---- v7: allow expired users only for pay_screenshot prompt ----
    FREE_STATES = ('pay_screenshot',)
    if not (is_owner(uid) or is_valid_admin(uid)) and aw not in FREE_STATES: return

    # ---- Single-user broadcast target ----
    if aw == 'broadcast_target' and is_owner(uid):
        try: tid = int(text.strip())
        except:
            await u.message.reply_text("❌ Send USER_ID (only number):", reply_markup=BACK_KB); return
        c.user_data['bc_uid'] = tid; c.user_data['awaiting'] = 'broadcast_capture'
        await u.message.reply_text(f"✅ Target set: `{tid}`\nNow send text / photo / video.", parse_mode='Markdown', reply_markup=BACK_KB); return

    # ---- Broadcast capture ----
    if aw == 'broadcast_capture' and is_owner(uid):
        c.user_data['awaiting'] = None
        tid = c.user_data.pop('bc_uid', None)
        await do_broadcast(u.message, c.bot, uid, text, only_user_id=tid)
        return

    # ---- v7: user sent text instead of screenshot ----
    if aw == 'pay_screenshot':
        c.user_data['awaiting'] = None
        await u.message.reply_text("📸 Please send a PHOTO (screenshot), not text.", reply_markup=expired_panel_keyboard()); return

    # ---- v7: plan add (owner) ----
    if aw == 'plan_add' and is_owner(uid):
        c.user_data['awaiting'] = None
        parts = [x.strip() for x in text.split('|')]
        if len(parts) != 4:
            await u.message.reply_text("❌ Format: `Button | Name | Price | Days`", parse_mode='Markdown', reply_markup=BACK_KB); return
        plans = load_plans()
        plans.append({'plan_id': uuid.uuid4().hex[:6], 'btn_name': parts[0], 'name': parts[1], 'price': float(parts[2]), 'days': int(parts[3])})
        save_plans(plans)
        await u.message.reply_text("✅ Plan added!", reply_markup=BACK_KB); return

    # ---- Custom admin time (typed) ----
    if aw == 'adm_custom_time':
        c.user_data['awaiting'] = None
        if not is_owner(uid): return
        t = c.user_data.pop('adm_target', None)
        if not t:
            await u.message.reply_text("❌ Session reset. Try again.", reply_markup=BACK_KB); return
        txt = text.strip(); minus = txt.startswith('-')
        try: nd = parse_duration(txt.lstrip('+-'))
        except Exception:
            await u.message.reply_text("❌ Format e.g. `45s`, `30m`, `2d 5h`, `1d`, `1w`", parse_mode='Markdown', reply_markup=BACK_KB); return
        if nd is None:
            await apply_admin_time(t, '+', None, text_ui=u.message)
        else:
            await apply_admin_time(t, '-' if minus else '+', nd, text_ui=u.message)
        return

    # ---- Special message text input ----
    if aw == 'spec_set_msg':
        c.user_data['awaiting'] = None
        aid = c.user_data.pop('spec_aid', None)
        if not aid or aid not in [a['id'] for a in get_all_accounts(uid)]:
            await u.message.reply_text("❌ reset, try again", reply_markup=BACK_KB); return
        set_special_msg(aid, text)
        nm = get_display_name_by_id(aid)
        await u.message.reply_text(f"✅ Special message pinned to {nm}.\nএখন এই id শুধু ওই মেসেজই spam করবে — অন্যরা স্বাভাবিক।", reply_markup=BACK_KB)
        return

    # ---- Admin add/edit - text form ----
    if aw == 'add_admin':
        c.user_data['awaiting'] = None
        if not is_owner(uid): return
        try: target, op, nd = parse_admin_cmd(text)
        except Exception:
            await u.message.reply_text("❌ Format: `USER_ID [+|-|=]TIME`\ne.g. `111 +2d 5h 30m`, `222 +1w`, `333 =perm`",
                                        parse_mode='Markdown', reply_markup=BACK_KB); return
        if target == OWNER_ID: await u.message.reply_text("❌ Owner cannot be edited.", reply_markup=BACK_KB); return
        await apply_admin_time(target, op, nd, text_ui=u.message)
        return
    if aw == 'admin_limit':
        c.user_data['awaiting'] = None
        if not is_owner(uid): return
        try:
            p = text.split(); t = int(p[0]); cap = int(p[1])
            if cap < 0: raise ValueError()
        except Exception:
            await u.message.reply_text("❌ `USER_ID NUMBER`", reply_markup=BACK_KB); return
        admins = load_admins(); found = False
        for a in admins:
            if a['user_id'] == t: a['max_accounts'] = (None if cap == 0 else cap); found = True
        if not found: await u.message.reply_text(f"❌ Admin not found: {t}", reply_markup=BACK_KB); return
        save_admins(admins)
        await u.message.reply_text(f"✅ {admin_label(t)} limit: {'unlimited' if cap == 0 else str(cap)}", reply_markup=BACK_KB); return
    if aw == 'def_add_name':
        c.user_data['awaiting'] = None; cfg = get_default_profile(); nm = cfg.get('names',[])
        nn = [x.strip() for x in text.split('\n') if x.strip()]; nm.extend(nn); cfg['names']=nm; save_default_profile(cfg)
        await u.message.reply_text(f"✅ Added {len(nn)} (total {len(nm)})", reply_markup=BACK_KB); return
    if aw == 'def_bio':
        c.user_data['awaiting'] = None; cfg = get_default_profile(); cfg['bio']=text; save_default_profile(cfg)
        await u.message.reply_text("✅ Bio saved", reply_markup=BACK_KB); return
    if aw == 'def_chan':
        c.user_data['awaiting'] = None; cfg = get_default_profile()
        cfg['channels']=[x.strip() for x in re.split(r'[\n,]+', text) if x.strip()]; save_default_profile(cfg)
        await u.message.reply_text("✅ Links saved", reply_markup=BACK_KB); return
    if aw == 'add_message':
        c.user_data['awaiting'] = None; m = load_messages_for(uid); m.append(text); save_messages_for(uid, m)
        await u.message.reply_text(f"✅ Added, total {len(m)}", reply_markup=BACK_KB); return
    if aw == 'phone_number':
        c.user_data['awaiting'] = None
        try:
            ph = text.strip()
            if not ph.startswith('+'): ph = '+' + ph
            if not re.match(r'^\+\d{7,15}$', ph):
                await u.message.reply_text("❌ Invalid! Example `+91XXXXXXXXXX`", reply_markup=BACK_KB); return
            reached, rm = account_limit_reached(uid)
            if reached: await u.message.reply_text(rm, reply_markup=BACK_KB); return
            if not API_ID_1 or not API_HASH_1:
                await u.message.reply_text("❌ API keys missing on server!", reply_markup=BACK_KB); return
            for k in [k for k,v in phone_login_states.items() if v.get('owner_id')==uid]:
                old = phone_login_states.pop(k, None)
                if old and old.get('client'):
                    try: await old['client'].disconnect()
                    except: pass
            sm = await u.message.reply_text("⏳ Sending OTP...", reply_markup=BACK_KB)
            client = None
            try:
                client = TelegramClient(StringSession(), API_ID_1, API_HASH_1, receive_updates=False)
                await client.connect(); sent = await client.send_code_request(ph)
                lid = gen_unique_id("plogin", uid)
                phone_login_states[lid] = {'phone':ph,'api_id':API_ID_1,'api_hash':API_HASH_1,'client':client,
                                           'owner_id':uid,'phone_code_hash':sent.phone_code_hash,'created':datetime.now()}
                c.user_data['login_id'] = lid; c.user_data['awaiting'] = 'otp_code'
                await sm.edit_text("✅ OTP sent! Enter the code:", reply_markup=BACK_KB)
            except FloodWaitError as fw:
                try:
                    if client: await client.disconnect()
                except: pass
                await sm.edit_text(f"⏳ Flood {fw.seconds}s", reply_markup=BACK_KB)
            except Exception as e:
                try:
                    if client: await client.disconnect()
                except: pass
                logger.error(f"code err {e}")
                await sm.edit_text(f"❌ {str(e)[:160]}", reply_markup=BACK_KB)
        except Exception as e:
            logger.error(f"top {e}")
            try: await u.message.reply_text(f"❌ {str(e)[:120]}", reply_markup=BACK_KB)
            except: pass
        return

    # ===== OTP CODE (single sign_in, no auto-resend, clean reset) =====
    if aw == 'otp_code':
        lid = c.user_data.get('login_id'); st = phone_login_states.get(lid) if lid else None
        if not st:
            c.user_data['awaiting'] = None
            await u.message.reply_text("⏳ Flow reset. Phone Login again.", reply_markup=BACK_KB); return
        code = text.strip().replace(' ','').replace('-','')
        if not code.isdigit():
            await u.message.reply_text("❌ digits only", reply_markup=BACK_KB); return
        client = st.get('client')
        try:
            if not client or not client.is_connected():
                client = TelegramClient(StringSession(), st['api_id'], st['api_hash'], receive_updates=False)
                await client.connect()
                st['client'] = client
        except Exception:
            pass
        try:
            await client.sign_in(phone=st['phone'], code=code, phone_code_hash=st['phone_code_hash'])
        except SessionPasswordNeededError:
            c.user_data['awaiting'] = '2fa_password'
            try: await u.message.reply_text("🔐 2FA password required:", reply_markup=BACK_KB)
            except: pass
            return
        except PhoneCodeInvalidError:
            try: await u.message.reply_text("❌ Wrong code. Recheck & send again.", reply_markup=BACK_KB)
            except: pass
            return
        except PhoneCodeExpiredError:
            try: await client.disconnect()
            except: pass
            phone_login_states.pop(lid, None); c.user_data.pop('login_id', None); c.user_data['awaiting'] = None
            try: await u.message.reply_text(
                "⚠️ Code expired/mismatch.\n\nবেশিরভাগ সময় একই বটের ২টা instance চললে এমন হয় — "
                "Render-এ পুরনো বিল্ড বন্ধ করুন।\n\nআবার চাইলে 📱 Phone Login থেকে নতুন শুরু করুন, "
                "নয়তো সোজা 🔑 Session String login ব্যবহার করুন (সবচেয়ে নির্ভরযোগ্য)।",
                reply_markup=BACK_KB)
            except: pass
            return
        except FloodWaitError as fw:
            try: await u.message.reply_text(f"⏳ Flood wait {fw.seconds}s — পরে চেষ্টা করুন।", reply_markup=BACK_KB)
            except: pass
            return
        except Exception as e:
            try: await u.message.reply_text(f"❌ {str(e)[:150]}", reply_markup=BACK_KB)
            except: pass
            return
        try:
            me = await client.get_me(); fresh = client.session.save(); await client.disconnect()
        except Exception as e:
            try: await u.message.reply_text(f"❌ {str(e)[:120]}", reply_markup=BACK_KB)
            except: pass
            return
        reached, rm = account_limit_reached(st['owner_id'])
        if reached:
            try: await u.message.reply_text(rm, reply_markup=BACK_KB)
            except: pass
            return
        au = load_auth_sessions()
        if any(s.get('owner_id')==st['owner_id'] and s.get('phone')==st['phone'] for s in au):
            try: await u.message.reply_text("❌ Number already added", reply_markup=BACK_KB)
            except: pass
            return
        nid = gen_unique_id("phone", st['owner_id']); fname = getattr(me,'first_name',None) or "User"
        au.append({'id':nid,'name':fname,'api_id':st['api_id'],'api_hash':st['api_hash'],'session_string':fresh,
                   'phone':st['phone'],'user_id':getattr(me,'id',None),'owner_id':st['owner_id'],
                   'login_time':datetime.now().isoformat()})
        save_auth_sessions(au); display_names[nid] = fname
        c.user_data['awaiting'] = None; c.user_data.pop('login_id', None)
        phone_login_states.pop(lid, None); refresh_account_stats(st['owner_id'])
        try: await u.message.reply_text(f"✅ Logged in! 👤 {fname}", reply_markup=BACK_KB)
        except: pass
        return

    # ===== 2FA password =====
    if aw == '2fa_password':
        lid = c.user_data.get('login_id'); st = phone_login_states.get(lid) if lid else None
        if not st:
            c.user_data['awaiting'] = None
            try: await u.message.reply_text("⏳ restart login", reply_markup=BACK_KB)
            except: pass
            return
        client = st['client']
        try: await client.sign_in(password=text.strip())
        except Exception as e:
            try: await u.message.reply_text(f"❌ {str(e)[:120]}", reply_markup=BACK_KB)
            except: pass
            return
        try:
            me = await client.get_me(); fresh = client.session.save(); await client.disconnect()
        except Exception as e:
            try: await u.message.reply_text(f"❌ {str(e)[:120]}", reply_markup=BACK_KB)
            except: pass
            return
        reached, rm = account_limit_reached(st['owner_id'])
        if reached:
            try: await u.message.reply_text(rm, reply_markup=BACK_KB)
            except: pass
            return
        au = load_auth_sessions()
        nid = gen_unique_id("phone", st['owner_id']); fname = getattr(me,'first_name',None) or "Unknown"
        au.append({'id':nid,'name':fname,'api_id':st['api_id'],'api_hash':st['api_hash'],'session_string':fresh,
                   'phone':st['phone'],'user_id':getattr(me,'id',None),'owner_id':st['owner_id'],
                   'login_time':datetime.now().isoformat()})
        save_auth_sessions(au); display_names[nid] = fname
        c.user_data['awaiting'] = None; c.user_data.pop('login_id', None)
        phone_login_states.pop(lid, None); refresh_account_stats(st['owner_id'])
        try: await u.message.reply_text(f"✅ 2FA done 👤 {fname}", reply_markup=BACK_KB)
        except: pass
        return
    if aw == 'add_account':
        c.user_data['awaiting'] = None
        try:
            reached, rm = account_limit_reached(uid)
            if reached: await u.message.reply_text(rm, reply_markup=BACK_KB); return
            sm = await u.message.reply_text("⏳ Testing...", reply_markup=BACK_KB)
            ok, name, _, fresh = await test_session_only(text)
            if not ok: await sm.edit_text("❌ Invalid/dead session", reply_markup=BACK_KB); return
            suc, data = add_dynamic_account(name, fresh, uid)
            await sm.edit_text(f"✅ {name} added!" if suc else f"❌ {data}", reply_markup=BACK_KB)
        except Exception as e: await u.message.reply_text(f"❌ {str(e)[:160]}", reply_markup=BACK_KB)
        return
    if aw == 'set_min':
        c.user_data['awaiting'] = None
        mn,mx,cyc = speed_for(uid)
        try:
            v = int(text)
            if 1 <= v < mx: set_speed(uid, min_i=v)
            else: raise ValueError()
        except: await u.message.reply_text(f"❌ 1-{mx-1} number", reply_markup=BACK_KB); return
        mn,mx,cyc = speed_for(uid); await u.message.reply_text(f"✅ Min {mn}s", reply_markup=BACK_KB)
    elif aw == 'set_max':
        c.user_data['awaiting'] = None
        mn,mx,cyc = speed_for(uid)
        try:
            v=int(text)
            if v > mn: set_speed(uid, max_i=v)
            else: raise ValueError()
        except: await u.message.reply_text(f"❌ > {mn}", reply_markup=BACK_KB); return
        mn,mx,cyc = speed_for(uid); await u.message.reply_text(f"✅ Max {mx}s", reply_markup=BACK_KB)
    elif aw == 'set_cycle':
        c.user_data['awaiting'] = None
        try:
            v=int(text)
            if v >= 5: set_speed(uid, cycle=v)
            else: raise ValueError()
        except: await u.message.reply_text("❌ >= 5", reply_markup=BACK_KB); return
        mn,mx,cyc = speed_for(uid); await u.message.reply_text(f"✅ Cycle {cyc}s", reply_markup=BACK_KB)

async def cancel_command(u, c):
    uid = u.effective_user.id; eu = u.effective_user
    record_user_info(uid, eu.first_name, eu.last_name, eu.username)
    c.user_data['awaiting'] = None; c.user_data.pop('login_id', None)
    await u.message.reply_text("❌ Cancelled.", reply_markup=BACK_KB)

async def main():
    global SHOW_START_TO_OTHERS
    await init_env_accounts()
    try: SHOW_START_TO_OTHERS = json.load(open(data_file)).get('show_start_to_others', True)
    except: pass
    load_data()
    for acc in get_all_accounts():
        aid = acc['id']; account_stats.setdefault(aid, {'sent':0,'running':False,'failed_channels':[]})
        stop_flags[aid] = False; display_names.setdefault(aid, acc.get('name'))
    valid = {OWNER_ID}
    for a in load_admins():
        if is_valid_admin(a['user_id']): valid.add(a['user_id'])
    for acc in get_all_accounts():
        if acc.get('owner_id', OWNER_ID) not in valid: stop_flags[acc['id']] = True
    for _ in range(5):
        try: httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true"); break
        except: await asyncio.sleep(2)
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    await app.initialize(); await app.start()
    asyncio.create_task(admin_expiry_checker())
    ok = False
    for i in range(5):
        try:
            await app.updater.start_polling(drop_pending_updates=True, timeout=30, read_timeout=30, connect_timeout=30, allowed_updates=Update.ALL_TYPES)
            print("✅ BOT RUNNING", flush=True); ok = True; break
        except Exception as e:
            if "Conflict" in str(e):
                try: httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true")
                except: pass
                await asyncio.sleep(10*(i+1))
            else: print(str(e)[:120], flush=True); await asyncio.sleep(5)
    if not ok: return
    try: await asyncio.Event().wait()
    except asyncio.CancelledError: pass
    finally:
        stop_all_accounts(); await asyncio.sleep(2)
        for fn in (app.updater.stop, app.stop, app.shutdown):
            try: await fn()
            except: pass

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"🌐 Flask on port {os.environ.get('PORT',10000)}", flush=True)
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("exit")
    except Exception as e:
        print(e, flush=True); import traceback; traceback.print_exc(); sys.exit(1)
