#!/usr/bin/env python3
"""
Telegram Mass Messaging Bot v1.1 FINAL (CLEAN MERGE, referral removed, OTP markdown-safe)
- Per-account SPECIAL MESSAGE
- Phone OTP login (single sign_in, no auto-resend loop) - Markdown-safe
- Auto-remove expired admins + 20s pre-expiry warning
- Owner custom admin time (+ add / - subtract / = set), 1s..any
- Targeted broadcast to a single user with error reporting
- Buy panel + QR payment screenshot -> owner Accept/Reject/Block
"""
import sys, os, asyncio, random, logging, json, threading, re, uuid
from datetime import datetime, timedelta
from telethon import TelegramClient, errors, functions
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.errors import (FloodWaitError, SessionPasswordNeededError,
    PhoneCodeInvalidError, PhoneCodeExpiredError, UserRestrictedError,
    AuthKeyUnregisteredError, UserDeactivatedError, UserDeactivatedBanError)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, filters)
from flask import Flask

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                    force=True, handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
API_ID_1 = int(os.environ.get("API_ID_1", "0")); API_HASH_1 = os.environ.get("API_HASH_1", "")
API_ID_2 = int(os.environ.get("API_ID_2", "0")); API_HASH_2 = os.environ.get("API_HASH_2", "")
API_ID_3 = int(os.environ.get("API_ID_3", "0")); API_HASH_3 = os.environ.get("API_HASH_3", "")
SESSION_1 = os.environ.get("SESSION_1", ""); SESSION_2 = os.environ.get("SESSION_2", ""); SESSION_3 = os.environ.get("SESSION_3", "")

DYNAMIC_ACCOUNTS_FILE = "dynamic_accounts.json"
AUTH_SESSIONS_FILE = "auth_sessions.json"
ADMINS_FILE = "admins.json"
PROFILE_FILE = "profile_configs.json"
NAME_FILE = "user_names.json"
USER_SPEED_FILE = "user_speed.json"
SPECIAL_MSG_FILE = "special_msgs.json"
PLANS_FILE = "plans.json"
QR_FILE = "qr_config.json"
BLOCKED_FILE = "blocked_users.json"
DEFAULT_PROFILE_KEY = "__default__"
data_file = "bot_data.json"
MESSAGE = os.environ.get("MESSAGE", "𝟭𝟬 𝗠𝗜𝗡 𝗩𝗖")
MIN_INTERVAL = int(os.environ.get("MIN_INTERVAL", "6"))
MAX_INTERVAL = int(os.environ.get("MAX_INTERVAL", "10"))
CYCLE_WAIT = int(os.environ.get("CYCLE_WAIT", "45"))
EXPIRED_MSG = "Your plan has expired. Contact admin 👉 @G18GamerBacko to buy a new one."
WARN_BEFORE_SEC = 20
try:
    _e = os.environ.get("ADMIN_ACCOUNT_LIMIT", "").strip()
    DEFAULT_ADMIN_LIMIT = int(_e) if _e else None
except Exception:
    DEFAULT_ADMIN_LIMIT = None

running_tasks, stop_flags, account_clients, account_stats = {}, {}, {}, {}
phone_login_states, display_names = {}, {}
ENV_ACCOUNTS = []
warned_users = set()
SHOW_START_TO_OTHERS = True
BACK_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='back_main')]])

# ---------------- file helpers ----------------
def load_json(fname, default):
    try:
        if os.path.exists(fname): return json.load(open(fname))
    except Exception: pass
    return default
def save_json(fname, data):
    try: json.dump(data, open(fname, 'w'), indent=2)
    except Exception: pass

def load_plans(): return load_json(PLANS_FILE, [])
def save_plans(p): save_json(PLANS_FILE, p)
def load_qr(): return load_json(QR_FILE, {})
def save_qr(d): save_json(QR_FILE, d)
def is_blocked(uid): return uid in load_json(BLOCKED_FILE, [])

def load_names(): return load_json(NAME_FILE, {})
def save_names(d=None):
    if d is None: d = load_names()
    save_json(NAME_FILE, d)
def record_user_info(uid, first="", last="", username=""):
    d = load_names(); old = d.get(str(uid), {})
    full = str(first or '').strip()
    if last: full = f"{full} {last}".strip()
    d[str(uid)] = {'name': full or old.get('name', ''),
                   'username': username or old.get('username', '')}
    save_names(d)
def admin_label(uid):
    info = load_names().get(str(uid))
    if info and info.get('name'): return f"{info['name']} (ID: {uid})"
    return f"ID: {uid}"
def get_names_short(uid):
    info = load_names().get(str(uid))
    if info and info.get('name'): return info['name'][:14]
    return str(uid)

def human_name(me):
    p = [getattr(me, 'first_name', '') or '', getattr(me, 'last_name', '') or '']
    n = ' '.join(x for x in p if x).strip()
    return n or f"User{getattr(me, 'id', '')}"

# ---------------- admins ----------------
def load_admins(): return load_json(ADMINS_FILE, [])
def save_admins(x): save_json(ADMINS_FILE, x)
def replace_admin(target, new_entry):
    admins = load_admins()
    for i, a in enumerate(admins):
        if a['user_id'] == target: admins[i] = new_entry; break
    save_admins(admins)
def get_admin(u):
    for a in load_admins():
        if a['user_id'] == u: return a
    return None
def is_owner(u): return u == OWNER_ID
def is_valid_admin(u):
    a = get_admin(u)
    if not a: return False
    exp = a.get('expires_at')
    if not exp: return True
    try: return datetime.fromisoformat(exp) > datetime.now()
    except Exception: return False
def remaining_time_str(e):
    if not e: return "♾️ Permanent"
    try: d = datetime.fromisoformat(e) - datetime.now()
    except Exception: return "?"
    if d.total_seconds() <= 0: return "⛔ EXPIRED"
    days, s = d.days, d.seconds
    h, m = s // 3600, (s % 3600) // 60
    p = []
    if days: p.append(f"{days}d")
    if h: p.append(f"{h}h")
    if m: p.append(f"{m}m")
    return " ".join(p) + " left" if p else "<1s"
def user_plan_time_str(uid):
    a = get_admin(uid)
    return remaining_time_str(a.get('expires_at')) if a else "❌ no plan"

def parse_duration(t):
    t = t.strip().lower()
    if t in ('perm','permanent','inf','unlimited','infinite'): return None
    for a, b in [('seconds','s'),('second','s'),('secs','s'),('sec','s'),
                 ('minutes','m'),('minute','m'),('mins','m'),('min','m'),
                 ('hours','h'),('hour','h'),('hrs','h'),('hr','h'),
                 ('days','d'),('day','d'),('weeks','w'),('week','w')]:
        t = t.replace(a, b)
    total, found = timedelta(), False
    for num, unit in re.findall(r'(\d+)\s*([dhms w])?', t + ' '):
        if not num.strip(): continue
        n = int(num); unit = (unit or 'm').strip()
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

# ---------------- speeds / messages / special ----------------
def load_user_speeds(): return load_json(USER_SPEED_FILE, {})
def save_user_speeds(d): save_json(USER_SPEED_FILE, d)
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
def load_special_msgs(): return load_json(SPECIAL_MSG_FILE, {})
def save_special_msgs(d): save_json(SPECIAL_MSG_FILE, d)
def get_special_msg(aid): return load_special_msgs().get(str(aid)) or ""
def set_special_msg(aid, msg):
    d = load_special_msgs()
    if msg: d[str(aid)] = msg
    else: d.pop(str(aid), None)
    save_special_msgs(d)
def gen_unique_id(p, o): return f"{p}_{o}_{uuid.uuid4().hex[:6]}"
def messages_file_for(u): return "messages.json" if is_owner(u) else f"messages_{u}.json"
def load_messages_for(u): return load_json(messages_file_for(u), [])
def save_messages_for(u, m): save_json(messages_file_for(u), m)
def get_random_message_for(u):
    m = load_messages_for(u)
    return random.choice(m) if m else MESSAGE

def load_profiles(): return load_json(PROFILE_FILE, {})
def save_profiles(p): save_json(PROFILE_FILE, p)
def get_default_profile(): return load_profiles().get(DEFAULT_PROFILE_KEY, {})
def save_default_profile(cfg):
    p = load_profiles(); p[DEFAULT_PROFILE_KEY] = cfg; save_profiles(p)

# ---------------- accounts storage ----------------
def load_auth_sessions(): return load_json(AUTH_SESSIONS_FILE, [])
def save_auth_sessions(s): save_json(AUTH_SESSIONS_FILE, s)
def load_dynamic_accounts(): return load_json(DYNAMIC_ACCOUNTS_FILE, [])
def save_dynamic_accounts(a): save_json(DYNAMIC_ACCOUNTS_FILE, a)

def acc_configs():
    return [('acc1', API_ID_1, API_HASH_1, SESSION_1),
            ('acc2', API_ID_2, API_HASH_2, SESSION_2),
            ('acc3', API_ID_3, API_HASH_3, SESSION_3)]

async def init_env_accounts():
    for acc_id, api_id, api_hash, session in acc_configs():
        if api_id and api_hash and session:
            try:
                c = TelegramClient(StringSession(session), api_id, api_hash, receive_updates=False)
                await c.start(); me = await c.get_me()
                n = human_name(me); await c.disconnect()
                ENV_ACCOUNTS.append({'id': acc_id, 'name': n, 'api_id': api_id, 'api_hash': api_hash,
                                     'session': session, 'type': 'env', 'phone': getattr(me, 'phone', ''),
                                     'owner_id': OWNER_ID})
                display_names[acc_id] = n
            except Exception as e:
                print(f"env {acc_id} failed: {str(e)[:60]}", flush=True)
            await asyncio.sleep(1)

def add_dynamic_account(name, ss, owner_id):
    accs = load_dynamic_accounts()
    for a in accs:
        if a['session'] == ss: return False, "Session already exists!"
    nid = gen_unique_id("acc_dyn", owner_id)
    accs.append({'id': nid, 'name': name, 'api_id': API_ID_1, 'api_hash': API_HASH_1,
                 'session': ss, 'type': 'dynamic', 'owner_id': owner_id})
    save_dynamic_accounts(accs); display_names[nid] = name
    return True, nid

def add_phone_auth_account(name, ss, owner_id, phone):
    aus = load_auth_sessions()
    nid = gen_unique_id("ph", owner_id)
    aus.append({'id': nid, 'name': name, 'api_id': API_ID_1, 'api_hash': API_HASH_1,
                'session_string': ss, 'type': 'phone_auth', 'phone': phone, 'owner_id': owner_id})
    save_auth_sessions(aus); display_names[nid] = name
    return nid

def get_all_accounts(user_id=None):
    dyn = load_dynamic_accounts()
    auth = [{'id': s['id'], 'name': s.get('name', f"User_{s.get('owner_id','?')}"),
             'api_id': s['api_id'], 'api_hash': s['api_hash'], 'session': s['session_string'],
             'type': 'phone_auth', 'phone': s.get('phone', ''), 'owner_id': s.get('owner_id', OWNER_ID)}
            for s in load_auth_sessions()]
    accs = ENV_ACCOUNTS + dyn + auth
    if user_id is None or user_id == OWNER_ID: return accs
    return [a for a in accs if a.get('owner_id') == user_id]

def remove_account_by_id(aid):
    global ENV_ACCOUNTS
    dyn = load_dynamic_accounts()
    for i, a in enumerate(dyn):
        if a['id'] == aid:
            dyn.pop(i); save_dynamic_accounts(dyn); display_names.pop(aid, None); return True
    au = load_auth_sessions()
    for i, a in enumerate(au):
        if a['id'] == aid:
            au.pop(i); save_auth_sessions(au); display_names.pop(aid, None); return True
    for i, a in enumerate(ENV_ACCOUNTS):
        if a['id'] == aid:
            ENV_ACCOUNTS.pop(i); display_names.pop(aid, None); return True
    return False

def get_display_name(acc): return display_names.get(acc.get('id')) or acc.get('name') or str(acc.get('id'))
def get_display_name_by_id(aid):
    for a in get_all_accounts():
        if a['id'] == aid: return get_display_name(a)
    return aid
def acc_by_id(aid):
    for a in get_all_accounts():
        if a['id'] == aid: return a
    return None
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
        except Exception: pass
    for acc in ENV_ACCOUNTS:
        if acc['id'] == acc_id: acc['name'] = new_name

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
            account_stats[aid] = {'sent': 0, 'running': False}
            stop_flags[aid] = False

# ---------------- telethon core ----------------
async def get_client(acc):
    aid = acc['id']; old = account_clients.get(aid)
    if old is not None:
        try:
            if old.is_connected(): return old
            await old.disconnect()
        except Exception: pass
        del account_clients[aid]
    c = TelegramClient(StringSession(acc['session']), acc['api_id'], acc['api_hash'], receive_updates=False)
    await c.start(); account_clients[aid] = c; return c
async def disconnect_client(aid):
    c = account_clients.pop(aid, None)
    if c:
        try: await c.disconnect()
        except Exception: pass
async def get_groups(client, retry=3):
    for _ in range(retry):
        try:
            dl = await client(GetDialogsRequest(offset_date=None, offset_id=0,
                                                offset_peer=InputPeerEmpty(), limit=200, hash=0))
            gs = []
            for d in dl.dialogs:
                try:
                    e = await client.get_entity(d.peer)
                    if hasattr(e, 'title'): gs.append(e)
                except Exception: pass
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
    except (UserRestrictedError, UserDeactivatedError, UserDeactivatedBanError,
            AuthKeyUnregisteredError) as e:
        return True, str(e)
    except Exception: return False, None
async def get_reply_target(client, group):
    try:
        async for m in client.iter_messages(group, limit=10):
            if m.from_id and m.sender and not getattr(m.sender, 'bot', False): return m
    except Exception: pass
    return None
async def notify_user(uid, t):
    try:
        b = Application.builder().token(BOT_TOKEN).build()
        await b.bot.send_message(chat_id=uid, text=t, parse_mode='Markdown')
    except Exception: pass
async def notify_plain(uid, t):
    try:
        b = Application.builder().token(BOT_TOKEN).build()
        await b.bot.send_message(chat_id=uid, text=t)
    except Exception as e:
        logger.error(f"notify_plain to {uid}: {e}")
async def join_link(client, link):
    link = link.strip().replace('http://', 'https://')
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
        try:
            await client(UpdateProfileRequest(first_name=name)); r.append("✅ Name"); persist_rename(aid, name)
        except Exception as e: r.append(f"❌ Name fail: {str(e)[:40]}")
        await asyncio.sleep(1)
    if bio:
        try:
            await client(UpdateProfileRequest(about=bio)); r.append("✅ Bio")
        except Exception as e: r.append(f"❌ Bio fail: {str(e)[:40]}")
        await asyncio.sleep(1)
    if photo:
        p = None
        try:
            tf = await bot.get_file(photo); p = f"prof_{aid}.jpg"
            await tf.download_to_drive(custom_path=p)
            with open(p, 'rb') as fh: up = await client.upload_file(fh)
            await client(UploadProfilePhotoRequest(file=up)); r.append("✅ Photo")
        except Exception as e: r.append(f"❌ Photo fail: {str(e)[:40]}")
        finally:
            if p and os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
        await asyncio.sleep(1)
    for lk in channels:
        try:
            await join_link(client, lk); r.append(f"✅ {lk}")
        except Exception as e: r.append(f"❌ {lk} fail: {str(e)[:30]}")
        await asyncio.sleep(0.5)
    return r

# ---------------- messaging engine ----------------
async def run_account_messaging(acc, owner):
    aid = acc['id']; stop_flags[aid] = False
    account_stats.setdefault(aid, {'sent': 0, 'running': False})
    account_stats[aid]['running'] = True
    try:
        client = await get_client(acc); me = await client.get_me()
        if getattr(me, 'first_name', None): persist_rename(aid, me.first_name)
        if not client.is_user_authorized():
            await notify_user(owner, f"🚨 *SESSION DEAD*\n{get_display_name(acc)}"); stop_account(aid); return
        res, _ = await is_account_restricted(client)
        if res:
            await notify_user(owner, f"🚨 *RESTRICTED*\n{get_display_name(acc)}"); stop_account(aid); return
        groups = await get_groups(client)
        if not groups:
            await notify_user(owner, f"⚠️ {get_display_name(acc)} - no groups")
            account_stats[aid]['running'] = False; return
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
                except (errors.UserBannedInChannelError, errors.ChatWriteForbiddenError,
                         errors.ChatAdminRequiredError):
                    failed.add(g.id)
                except errors.RPCError as e:
                    if any(x in str(e).lower() for x in ['ban','restrict','forbidden','write','permission']):
                        failed.add(g.id)
                except Exception as e:
                    if any(x in str(e).lower() for x in ['ban','restrict','forbidden','admin',"can't write"]):
                        failed.add(g.id)
                await asyncio.sleep(random.randint(mn, mx))
            res, _ = await is_account_restricted(client)
            if res:
                await notify_user(owner, f"🚨 *RESTRICTED*\n{get_display_name(acc)}"); stop_account(aid); return
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
                        if getattr(me, 'first_name', None): persist_rename(aid, me.first_name)
                except Exception as e: logger.error(f"reconnect:{e}")
    except asyncio.CancelledError:
        pass
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
        except Exception: pass
    if aid in account_stats: account_stats[aid]['running'] = False
def stop_accounts_of(u):
    for a in get_all_accounts(u): stop_account(a['id'])

# ---------------- expiry checker ----------------
async def admin_expiry_checker():
    while True:
        try:
            await asyncio.sleep(1)
            admins = load_admins(); keep = []; changed = False
            for a in admins:
                uid = a['user_id']; exp = a.get('expires_at')
                if not exp: keep.append(a); continue
                try: rem = (datetime.fromisoformat(exp) - datetime.now()).total_seconds()
                except Exception: rem = 999999
                if rem <= 0:
                    changed = True
                    for acc in get_all_accounts(uid):
                        if account_stats.get(acc['id'], {}).get('running', False): stop_account(acc['id'])
                        await disconnect_client(acc['id'])
                    try: await notify_plain(uid, f"⛔ Plan expired\n\n{EXPIRED_MSG}")
                    except Exception: pass
                    warned_users.discard(uid)
                else:
                    keep.append(a)
                    if rem <= WARN_BEFORE_SEC and uid != OWNER_ID and uid not in warned_users:
                        warned_users.add(uid)
                        try: await notify_plain(uid, f"⏳ Your plan expires in {int(rem)} seconds!\n\n{EXPIRED_MSG}")
                        except Exception: pass
            if changed: save_admins(keep)
            valid = {OWNER_ID}
            for a in keep:
                exp = a.get('expires_at')
                if not exp: valid.add(a['user_id']); continue
                try:
                    if datetime.fromisoformat(exp) > datetime.now(): valid.add(a['user_id'])
                except Exception: valid.add(a['user_id'])
            for acc in get_all_accounts():
                oid = acc.get('owner_id', OWNER_ID)
                if oid not in valid and account_stats.get(acc['id'], {}).get('running', False):
                    stop_account(acc['id']); await disconnect_client(acc['id'])
        except Exception as e:
            logger.error(f"expiry:{e}"); await asyncio.sleep(5)

# ---------------- menus ----------------
def expired_panel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton(p['btn_name'], callback_data=f"buy_{p['plan_id']}")]
                                 for p in load_plans()])
def expired_panel_text():
    lines = ["🚫 *Bot access deleted!*\n\nYour plan has expired.\nContact admin 👉 @G18GamerBacko\n\n💎 *Available Plans:*"]
    for p in load_plans():
        lines.append(f"\n▫️ {p['name']} — ₹{p['price']} / {p['days']}d")
    return "\n".join(lines)
def main_menu_keyboard(u):
    rows = [[InlineKeyboardButton("▶️ Start All", callback_data='start_all'),
             InlineKeyboardButton("⏹️ Stop All", callback_data='stop_all')],
            [InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
            [InlineKeyboardButton("🔑 Session Login", callback_data='add_account')],
            [InlineKeyboardButton("📱 Phone Login", callback_data='phone_login')],
            [InlineKeyboardButton("🗑️ Delete Account", callback_data='delete_account')],
            [InlineKeyboardButton("🎨 Profile Setup", callback_data='profile_setup')]]
    if is_owner(u):
        rows.append([InlineKeyboardButton("👑 Admin Panel", callback_data='admin_panel')])
    return InlineKeyboardMarkup(rows)
def main_menu_text(u):
    accs = get_all_accounts(u)
    run = sum(1 for a in accs if account_stats.get(a['id'], {}).get('running', False))
    sent = sum(account_stats.get(a['id'], {}).get('sent', 0) for a in accs)
    mn, mx, cyc = speed_for(u)
    role = "👑 Owner" if is_owner(u) else "👤 Admin"
    extra = ""
    if not is_owner(u):
        a = get_admin(u)
        exp = f"\n⏳ Time: {remaining_time_str(a.get('expires_at') if a else None)}"
        cap = admin_max_accounts(u); cur = owner_acc_count(u)
        lim = f"\n🔢 Accounts: {cur}" if cap is None else f"\n🔢 Accounts: {cur}/{cap}"
        extra = exp + lim
    return (f"✨ *Bot v1.1 FINAL* ✨\n{role}{extra}\n\n"
            f"📊 Accounts: {len(accs)} (Running: {run})\n"
            f"⚡ Speed: {mn}-{mx}s | 🔄 Cycle: {cyc}s\n📨 Sent: {sent}")

async def start_command(u, c):
    uid = u.effective_user.id; eu = u.effective_user
    record_user_info(uid, eu.first_name, eu.last_name, eu.username)
    if is_blocked(uid):
        await u.message.reply_text("🚫 You are blocked. Contact admin 👉 @G18GamerBacko"); return
    if is_owner(uid) or is_valid_admin(uid):
        refresh_account_stats(uid); preload_display_names(get_all_accounts(uid))
        await u.message.reply_text(main_menu_text(uid), parse_mode='Markdown',
                                   reply_markup=main_menu_keyboard(uid))
        return
    await u.message.reply_text(expired_panel_text(), parse_mode='Markdown',
                               reply_markup=expired_panel_keyboard())
async def cancel_cmd(u, c):
    c.user_data.clear()
    uid = u.effective_user.id
    await u.message.reply_text("❌ Cancelled.",
                               reply_markup=(main_menu_keyboard(uid) if (is_owner(uid) or is_valid_admin(uid)) else expired_panel_keyboard()))

async def activate_plan(user_id, days, plan_name="plan"):
    nd = datetime.now() + timedelta(days=days)
    admins = load_admins(); a = get_admin(user_id)
    if a is None:
        admins.append({'user_id': user_id, 'expires_at': nd.isoformat(),
                       'added_at': datetime.now().isoformat(), 'updated_at': datetime.now().isoformat(),
                       'max_accounts': DEFAULT_ADMIN_LIMIT})
    else:
        cur = None
        try: cur = datetime.fromisoformat(a['expires_at']) if a.get('expires_at') else None
        except Exception: cur = None
        rem = (cur - datetime.now()) if (cur and cur > datetime.now()) else timedelta(0)
        a['expires_at'] = (datetime.now() + rem + timedelta(days=days)).isoformat()
        a['updated_at'] = datetime.now().isoformat()
        for i, x in enumerate(admins):
            if x['user_id'] == user_id: admins[i] = a
    save_admins(admins)
    warned_users.discard(user_id)
    gg = get_admin(user_id)
    valid = remaining_time_str(gg.get('expires_at') if gg else None)
    try:
        await notify_plain(user_id,
            f"✅ Payment confirmed!\n\n💎 Plan: {plan_name}\n⏳ Your validity: {valid}\n\nCLICK👉 /start")
    except Exception as e:
        logger.error(f"confirm msg: {e}")

async def apply_admin_time(target, op, nd, q=None, text_ui=None):
    now = datetime.now(); admins = load_admins(); a = get_admin(target)
    if a is None:
        a = {'user_id': target, 'expires_at': None if nd is None else nd.isoformat(),
             'added_at': now.isoformat(), 'updated_at': now.isoformat(), 'max_accounts': DEFAULT_ADMIN_LIMIT}
        admins.append(a); save_admins(admins)
        resp = f"✅ Admin added: {admin_label(target)}\n⏳ Time: {remaining_time_str(a['expires_at'])}"
    else:
        if nd is None:
            if op == '-': a['expires_at'] = now.isoformat(); chg = "expired now"
            else: a['expires_at'] = None; chg = "♾️ Permanent"
        else:
            cur = None
            try: cur = datetime.fromisoformat(a['expires_at']) if a.get('expires_at') else None
            except Exception: cur = None
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
        except Exception: pass
    elif q is not None:
        try: await q.edit_message_text(resp, parse_mode='Markdown', reply_markup=BACK_KB)
        except Exception: pass
    return resp

def broadcast_targets():
    ids = [OWNER_ID]
    for a in load_admins():
        if is_valid_admin(a['user_id']) and a['user_id'] != OWNER_ID:
            ids.append(a['user_id'])
    return list(dict.fromkeys(ids))

async def do_broadcast(reply_target, bot, uid, caption="", media_file=None, media_type="text", only_user_id=None):
    if not is_owner(uid): return
    targets = [only_user_id] if only_user_id is not None else broadcast_targets()
    if not targets:
        try: await reply_target.reply_text("❌ No target available", reply_markup=BACK_KB)
        except Exception: pass
        return
    ok = 0; fails = []
    for t in targets:
        try:
            if media_type == 'photo': await bot.send_photo(chat_id=t, photo=media_file, caption=caption)
            elif media_type == 'video': await bot.send_video(chat_id=t, video=media_file, caption=caption)
            elif media_type == 'animation': await bot.send_animation(chat_id=t, animation=media_file, caption=caption)
            else: await bot.send_message(chat_id=t, text=caption)
            ok += 1
        except Exception as e:
            es = str(e)
            if 'initiate conversation' in es or 'chat not found' in es.lower():
                fails.append(f"ID {t}: user ne /start kore nai")
            elif 'blocked' in es.lower() or 'forbidden' in es.lower():
                fails.append(f"ID {t}: user bot block koreche")
            else: fails.append(f"ID {t}: {es[:60]}")
            logger.error(f"bc to {t}: {es[:100]}")
    who = "single user" if only_user_id is not None else "all admins"
    txt = f"📢 Broadcast: ✅ {ok} delivered ({who})"
    if fails: txt += "\n\n❌ Failed:\n" + "\n".join(fails[:10])
    if only_user_id is not None and ok == 0:
        txt += "\n\n💡 Target user ke AGE bot e /start dite hobe."
    try: await reply_target.reply_text(txt, reply_markup=BACK_KB)
    except Exception: pass

async def safe_edit(q, bot, txt, kb=None):
    try:
        await q.edit_message_text(txt, reply_markup=kb); return
    except Exception: pass
    try:
        await q.edit_message_caption(caption=txt, reply_markup=kb); return
    except Exception: pass
    try:
        await bot.send_message(q.from_user.id, txt, reply_markup=kb)
    except Exception: pass

# ---------------- button handler ----------------
async def button_click(u, c):
    global SHOW_START_TO_OTHERS
    q = u.callback_query; await q.answer(); uid = q.from_user.id
    frm = q.from_user
    record_user_info(uid, frm.first_name, frm.last_name, frm.username)
    d = q.data
    ALLOWED_FREE_PREFIXES = ('buy_', 'paid_', 'back_start', 'payok_', 'payno_', 'payblock_')
    is_free = any(d.startswith(x) for x in ALLOWED_FREE_PREFIXES)
    if not (is_owner(uid) or is_valid_admin(uid)) and not is_free:
        if SHOW_START_TO_OTHERS: await q.edit_message_text("⛔ Access denied / expired.")
        else: await q.edit_message_text(" ")
        return

    if d.startswith('buy_'):
        pid = d.replace('buy_', '')
        plan = next((p for p in load_plans() if p['plan_id'] == pid), None)
        if not plan:
            await q.edit_message_text("❌ Plan unavailable", reply_markup=expired_panel_keyboard()); return
        kb = [[InlineKeyboardButton("✅ I Have Paid", callback_data=f'paid_{pid}'),
               InlineKeyboardButton("🔙 Back", callback_data='back_start')]]
        cap = f"\n\n💎 {plan['name']}\n💸 Price: ₹{plan['price']}\n⏳ Duration: {plan['days']} days"
        qr = load_qr()
        try: await q.message.delete()
        except Exception: pass
        if qr.get('photo'):
            await c.bot.send_photo(uid, photo=qr['photo'], caption="💳 Pay via this QR" + cap,
                                   parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        else:
            await c.bot.send_message(uid, "💳 Pay to admin (QR not set yet)" + cap,
                                     parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'back_start':
        try: await q.message.delete()
        except Exception: pass
        if is_owner(uid) or is_valid_admin(uid):
            refresh_account_stats(uid); preload_display_names(get_all_accounts(uid))
            await c.bot.send_message(uid, main_menu_text(uid), parse_mode='Markdown',
                                     reply_markup=main_menu_keyboard(uid))
        else:
            await c.bot.send_message(uid, expired_panel_text(), parse_mode='Markdown',
                                     reply_markup=expired_panel_keyboard())
    elif d.startswith('paid_'):
        pid = d.replace('paid_', '')
        plan = next((p for p in load_plans() if p['plan_id'] == pid), None)
        if not plan: return
        c.user_data['awaiting'] = 'pay_screenshot'; c.user_data['pay_plan'] = pid
        try: await q.message.delete()
        except Exception: pass
        await c.bot.send_message(uid, "📸 Please send your payment screenshot.", reply_markup=BACK_KB)
    elif d.startswith('payok_'):
        if not is_owner(uid): return
        try:
            _, buyer_s, pid = d.split('_', 2); buyer = int(buyer_s)
            plan = next((p for p in load_plans() if p['plan_id'] == pid), None)
            if not plan: await safe_edit(q, c.bot, "❌ Plan gone"); return
            await activate_plan(buyer, int(plan['days']), plan['name'])
            await safe_edit(q, c.bot, f"✅ Accepted payment of {buyer} ({plan['name']})")
        except Exception as e:
            logger.error(f"payok: {e}"); await safe_edit(q, c.bot, f"❌ Error: {str(e)[:100]}")
    elif d.startswith('payno_'):
        if not is_owner(uid): return
        try:
            buyer = int(d.split('_')[1])
            await notify_plain(buyer, "❌ Your payment was rejected. Contact admin 👉 @G18GamerBacko")
            await safe_edit(q, c.bot, "❌ Rejected & user notified")
        except Exception as e:
            await safe_edit(q, c.bot, f"❌ Error: {str(e)[:100]}")
    elif d.startswith('payblock_'):
        if not is_owner(uid): return
        try:
            buyer = int(d.split('_')[1])
            await notify_plain(buyer, "🚫 You have been blocked for fake payment.")
            bl = load_json(BLOCKED_FILE, [])
            if buyer not in bl: bl.append(buyer); save_json(BLOCKED_FILE, bl)
            await safe_edit(q, c.bot, "🚫 User blocked")
        except Exception as e:
            await safe_edit(q, c.bot, f"❌ Error: {str(e)[:100]}")

    elif d == 'start_all':
        p = []
        for a in get_all_accounts(uid):
            if account_stats.get(a['id'], {}).get('running', False):
                p.append(f"✅ Already running: {get_display_name(a)}")
            else:
                stop_flags[a['id']] = False
                running_tasks[a['id']] = asyncio.create_task(run_account_messaging(a, uid))
                p.append(f"▶️ Started: {get_display_name(a)}")
        await q.edit_message_text("\n".join(p) if p else "❌ No accounts", reply_markup=BACK_KB)
    elif d == 'stop_all':
        p = []
        for a in get_all_accounts(uid):
            if account_stats.get(a['id'], {}).get('running', False):
                stop_account(a['id']); p.append(f"⏹️ Stopping: {get_display_name(a)}")
            else: p.append(f"⏸️ Stopped: {get_display_name(a)}")
        await q.edit_message_text("\n".join(p) if p else "✅ Nothing running", reply_markup=BACK_KB)
    elif d == 'status':
        accs = get_all_accounts(uid); txt = "📊 *Status*\n\n"
        for i, a in enumerate(accs, 1):
            st = '🟢 RUNNING' if account_stats.get(a['id'], {}).get('running', False) else '🔴 STOPPED'
            txt += f"#{i} · {get_display_name(a)}\n ↳ {st} | Sent: {account_stats.get(a['id'], {}).get('sent', 0)}\n"
        if not accs: txt += "_None_\n"
        txt += f"\n📨 Total: {sum(account_stats.get(a['id'], {}).get('sent', 0) for a in accs)}"
        await q.edit_message_text(txt, parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'settings':
        mn, mx, cyc = speed_for(uid)
        kb = [[InlineKeyboardButton("📊 Status", callback_data='status')],
              [InlineKeyboardButton("📝 Messages", callback_data='message_list'),
               InlineKeyboardButton("⏱️ Speed", callback_data='edit_speed')],
              [InlineKeyboardButton("📌 Special Msg", callback_data='special_msg_menu')],
              [InlineKeyboardButton("🔙 Back", callback_data='back_main')]]
        await q.edit_message_text(f"⚙️ *Settings*\n⚡ Speed: {mn}-{mx}s | 🔄 Cycle: {cyc}s",
                                  parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'message_list':
        m = load_messages_for(uid)
        txt = f"📝 *Your Messages* ({len(m)}):\n" + "".join(f"`{x[:40]}`\n\n" for x in m[:10])
        kb = [[InlineKeyboardButton("➕ Add", callback_data='add_message'),
               InlineKeyboardButton("🗑️ Delete", callback_data='delete_message_menu')],
              [InlineKeyboardButton("🔄 Reset", callback_data='reset_messages')],
              [InlineKeyboardButton("🔙 Back", callback_data='settings')]]
        await q.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'edit_speed':
        mn, mx, cyc = speed_for(uid)
        kb = [[InlineKeyboardButton(f"⏱️ Min {mn}s", callback_data='set_min'),
               InlineKeyboardButton(f"⏱️ Max {mx}s", callback_data='set_max')],
              [InlineKeyboardButton(f"🔄 Cycle {cyc}s", callback_data='set_cycle')],
              [InlineKeyboardButton("🔙 Back", callback_data='settings')]]
        await q.edit_message_text("⏱️ *Speed Settings*", parse_mode='Markdown',
                                  reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'add_message': c.user_data['awaiting'] = 'add_message'; await q.edit_message_text("✏️ Send the new message text:", reply_markup=BACK_KB)
    elif d == 'delete_message_menu':
        m = load_messages_for(uid)
        if not m: await q.edit_message_text("❌ No messages yet", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"🗑️ {i+1}. {x[:20]}", callback_data=f'del_msg_{i}')] for i, x in enumerate(m)]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='message_list')])
        await q.edit_message_text("Which one to delete?", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('del_msg_'):
        m = load_messages_for(uid); i = int(d.replace('del_msg_', ''))
        if 0 <= i < len(m): m.pop(i); save_messages_for(uid, m)
        await q.edit_message_text("🗑️ Deleted", reply_markup=BACK_KB)
    elif d == 'reset_messages': save_messages_for(uid, [MESSAGE]); await q.edit_message_text("🔄 Reset done", reply_markup=BACK_KB)
    elif d == 'set_min': c.user_data['awaiting'] = 'set_min'; await q.edit_message_text("⏱️ Enter Min seconds:", reply_markup=BACK_KB)
    elif d == 'set_max': c.user_data['awaiting'] = 'set_max'; await q.edit_message_text("⏱️ Enter Max seconds:", reply_markup=BACK_KB)
    elif d == 'set_cycle': c.user_data['awaiting'] = 'set_cycle'; await q.edit_message_text("🔄 Enter cycle seconds (5+):", reply_markup=BACK_KB)

    elif d == 'special_msg_menu':
        accs = get_all_accounts(uid)
        if not accs: await q.edit_message_text("❌ No accounts", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"{'📌' if get_special_msg(a['id']) else '▫️'} #{i} · {get_display_name(a)[:16]}",
                                    callback_data=f'spec_show_{a["id"]}')] for i, a in enumerate(accs, 1)]
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
        await q.edit_message_text("✏️ Send the SPECIAL message text now.", parse_mode='Markdown', reply_markup=BACK_KB)
    elif d.startswith('spec_clear_'):
        aid = d.replace('spec_clear_', '')
        if aid not in [a['id'] for a in get_all_accounts(uid)]:
            await q.edit_message_text("⛔ Not your account", reply_markup=BACK_KB); return
        set_special_msg(aid, ""); await q.edit_message_text("🗑️ Special message removed.", reply_markup=BACK_KB)

    elif d == 'profile_setup':
        accs = get_all_accounts(uid)
        if not accs: await q.edit_message_text("❌ No accounts", reply_markup=BACK_KB); return
        cfg = get_default_profile()
        kb = [[InlineKeyboardButton(f"⚙️ Profile Config (Names:{len(cfg.get('names',[]))}|Logos:{len(cfg.get('photos',[]))})", callback_data='profdefault')],
              [InlineKeyboardButton("⚡ Apply to ALL accounts", callback_data='profapply_all')],
              [InlineKeyboardButton("🔙 Back", callback_data='back_main')]]
        await q.edit_message_text(f"🎨 *Profile Setup*\nAccounts: {len(accs)}", parse_mode='Markdown',
                                  reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'profdefault':
        cfg = get_default_profile(); nm = cfg.get('names', []); ph = cfg.get('photos', []); ch = cfg.get('channels', [])
        txt = (f"⚙️ *Profile Config*\n📝 Names ({len(nm)})\n🖼️ Logos: {len(ph)} | 📄 Bio: `{cfg.get('bio','-')}`"
               f"\n📢 Channels ({len(ch)})\n" + "".join(f" {x}\n" for x in ch[:10]))
        kb = [[InlineKeyboardButton("➕ Add Name", callback_data='def_add_name'), InlineKeyboardButton("➖ Del Name", callback_data='def_del_name')],
              [InlineKeyboardButton("🖼️ Add Logo", callback_data='def_add_photo'), InlineKeyboardButton("🗑️ Del Logo", callback_data='def_del_photo')],
              [InlineKeyboardButton("📄 Set Bio", callback_data='def_bio')],
              [InlineKeyboardButton("📢 Channels", callback_data='def_chan')],
              [InlineKeyboardButton("🔄 Reset", callback_data='def_reset')],
              [InlineKeyboardButton("🔙 Back", callback_data='profile_setup')]]
        await q.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'def_add_name': c.user_data['awaiting'] = 'def_add_name'; await q.edit_message_text("📝 Send names, one per line:", reply_markup=BACK_KB)
    elif d == 'def_del_name':
        nm = get_default_profile().get('names', [])
        if not nm: await q.edit_message_text("❌ No names", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"➖ {x[:25]}", callback_data=f'def_delname_{i}')] for i, x in enumerate(nm)]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='profdefault')])
        await q.edit_message_text("Which?", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('def_delname_'):
        cfg = get_default_profile(); nm = cfg.get('names', []); i = int(d.replace('def_delname_', ''))
        if 0 <= i < len(nm): nm.pop(i); cfg['names'] = nm; save_default_profile(cfg)
        await q.edit_message_text("🗑️ Deleted", reply_markup=BACK_KB)
    elif d == 'def_add_photo': c.user_data['awaiting'] = 'def_add_photo'; await q.edit_message_text("🖼️ Send a photo:", reply_markup=BACK_KB)
    elif d == 'def_del_photo':
        ph = get_default_profile().get('photos', [])
        if not ph: await q.edit_message_text("❌ No logos", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"🗑️ Logo #{i+1}", callback_data=f'def_delphoto_{i}')] for i in range(len(ph))]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data='profdefault')])
        await q.edit_message_text("Which?", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith('def_delphoto_'):
        cfg = get_default_profile(); ph = cfg.get('photos', []); i = int(d.replace('def_delphoto_', ''))
        if 0 <= i < len(ph): ph.pop(i); cfg['photos'] = ph; save_default_profile(cfg)
        await q.edit_message_text("🗑️ Deleted", reply_markup=BACK_KB)
    elif d == 'def_bio': c.user_data['awaiting'] = 'def_bio'; await q.edit_message_text("📄 Send bio text:", reply_markup=BACK_KB)
    elif d == 'def_chan': c.user_data['awaiting'] = 'def_chan'; await q.edit_message_text("📢 Send channel links (line wise):", reply_markup=BACK_KB)
    elif d == 'def_reset': save_default_profile({}); await q.edit_message_text("🔄 Reset done", reply_markup=BACK_KB)
    elif d == 'profapply_all':
        accs = get_all_accounts(uid); cfg = get_default_profile()
        nm = cfg.get('names', []); ph = cfg.get('photos', []); bio = cfg.get('bio', ''); ch = cfg.get('channels', [])
        if not accs or (not nm and not ph and not bio and not ch):
            await q.edit_message_text("❌ Add config first!", reply_markup=BACK_KB); return
        total = len(accs); prog = {'done': 0, 'lines': {}}
        sm = await q.edit_message_text("⚡ Applying 0%")
        async def one(i, acc):
            try:
                rr = await apply_profile(acc, nm[i % len(nm)] if nm else '', ph[i % len(ph)] if ph else None, bio, ch, bot=c.bot)
                ok = sum(1 for x in rr if x.startswith('✅'))
                prog['lines'][i] = f"#{i+1} · {get_display_name(acc)[:15]}: ok {ok}"
            except Exception as e:
                prog['lines'][i] = f"#{i+1}: fail {str(e)[:30]}"
            prog['done'] += 1
        tasks = [asyncio.create_task(one(i, a)) for i, a in enumerate(accs)]
        while any(not t.done() for t in tasks):
            pct = int(prog['done'] * 100 / total)
            try: await sm.edit_text(f"{'█' * (pct // 10)}{'░' * (10 - pct // 10)} {pct}%")
            except Exception: pass
            await asyncio.sleep(2)
        await asyncio.gather(*tasks, return_exceptions=True)
        await sm.edit_text("✅ *Done!*\n\n" + "\n".join(prog['lines'][i] for i in sorted(prog['lines'])),
                           parse_mode='Markdown', reply_markup=BACK_KB)

    elif d == 'admin_panel':
        if not is_owner(uid): return
        kb = [[InlineKeyboardButton("➕ Add / Edit Admin", callback_data='add_admin'),
               InlineKeyboardButton("📋 Admin List", callback_data='admin_list')],
              [InlineKeyboardButton("🔢 Set Account Limit", callback_data='set_admin_limit'),
               InlineKeyboardButton("💰 Plans & QR", callback_data='plans_menu')],
              [InlineKeyboardButton(f"👻 Start-msg: {'ON' if SHOW_START_TO_OTHERS else 'OFF'}", callback_data='toggle_startmsg')],
              [InlineKeyboardButton("📢 Broadcast", callback_data='broadcast_menu')],
              [InlineKeyboardButton("🔙 Back", callback_data='back_main')]]
        await q.edit_message_text("👑 *Admin Panel* ✨ _(Owner only)_", parse_mode='Markdown',
                                  reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'broadcast_menu':
        if not is_owner(uid): return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 To All Admins", callback_data='bc_all')],
                                   [InlineKeyboardButton("👤 To One User", callback_data='bc_one')],
                                   [InlineKeyboardButton("🔙 Back", callback_data='admin_panel')]])
        await q.edit_message_text("📨 *Broadcast*\nChoose target:", parse_mode='Markdown', reply_markup=kb)
    elif d == 'bc_all':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'broadcast_capture'; c.user_data.pop('bc_uid', None)
        await q.edit_message_text("📢 Now send text / photo / video — goes to all admins.", parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'bc_one':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'broadcast_target'; c.user_data.pop('bc_uid', None)
        await q.edit_message_text("👤 Send the target USER_ID (only number):", parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'set_admin_limit':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'admin_limit'
        await q.edit_message_text("🔢 Format: `USER_ID NUMBER`\n(0 = unlimited)", parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'add_admin':
        if not is_owner(uid): return
        c.user_data['awaiting'] = 'add_admin'
        await q.edit_message_text("➕ *Add / Edit Admin*\n\nFormat:\n`USER_ID [+|-|=]TIME`\n"
                                  "🔸 `111 +2d` → add 2 days\n🔸 `111 +2d 5h 30m`\n🔸 `111 -1d 2h`\n"
                                  "🔸 `111 =45s`\n🔸 `111 =perm` → permanent\n🔸 `111 +1w`",
                                  parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'toggle_startmsg':
        if not is_owner(uid): return
        SHOW_START_TO_OTHERS = not SHOW_START_TO_OTHERS; save_data()
        await q.edit_message_text(f"👻 Show msg to non-admins on old menu press: {'ON' if SHOW_START_TO_OTHERS else 'OFF'}", reply_markup=BACK_KB)
    elif d == 'admin_list':
        if not is_owner(uid): return
        admins = load_admins()
        if not admins: await q.edit_message_text("❌ No admins yet", reply_markup=BACK_KB); return
        txt = "📋 *Admins*\n\n"; kb = []
        for a in admins:
            accs = get_all_accounts(a['user_id'])
            cap = a.get('max_accounts')
            cap_str = f"🔢 Accounts: {len(accs)}" if not cap else f"🔢 Accounts: {len(accs)}/{cap}"
            txt += f"👤 {admin_label(a['user_id'])}\n ⏳ {remaining_time_str(a.get('expires_at'))}\n {cap_str}\n\n"
            kb.append([InlineKeyboardButton(f"🕐 Edit · {get_names_short(a['user_id'])} ({a['user_id']})", callback_data=f'admin_edit_{a["user_id"]}'),
                       InlineKeyboardButton("🗑️", callback_data=f'del_admin_{a["user_id"]}')])
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
        await q.edit_message_text("➕ Send plan:\n`Button Name | Plan Name | PRICE | DAYS`", parse_mode='Markdown', reply_markup=BACK_KB)
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
        t = int(d.replace('admin_edit_', ''))
        a = get_admin(t)
        if not a: await q.edit_message_text("❌ Not an admin", reply_markup=BACK_KB); return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕30d", callback_data=f'admop_{t}_+30'), InlineKeyboardButton("➕100d", callback_data=f'admop_{t}_+100')],
            [InlineKeyboardButton("➖10d", callback_data=f'admop_{t}_-10'), InlineKeyboardButton("➖30d", callback_data=f'admop_{t}_-30')],
            [InlineKeyboardButton("✍️ Custom Time (+/-)", callback_data=f'adm_time_{t}')],
            [InlineKeyboardButton("♾️ Permanent", callback_data=f'admop_{t}_=perm'), InlineKeyboardButton("⛔ Expire", callback_data=f'admop_{t}_=0')],
            [InlineKeyboardButton("🔙 Back", callback_data='admin_list')]])
        accs = get_all_accounts(t)
        names = "\n".join(f" • {get_display_name(x)}" for x in accs[:10]) or "  _none_"
        await q.edit_message_text(f"👤 {admin_label(t)}\n⏳ {remaining_time_str(a.get('expires_at'))}\n📊 Accounts:\n{names}",
                                  parse_mode='Markdown', reply_markup=kb)
    elif d.startswith('adm_time_'):
        if not is_owner(uid): return
        try: t = int(d.replace('adm_time_', ''))
        except Exception:
            await q.edit_message_text("❌ Parse error", reply_markup=BACK_KB); return
        c.user_data['awaiting'] = 'adm_custom_time'; c.user_data['adm_target'] = t
        await q.edit_message_text("⏳ *Custom Time*\n\n➕ barano: `+45s`, `+30m`, `+2d 5h`, `+1w`\n"
                                  "➖ komano: `-30m`, `-1d`, `-2d 5h`\n⚖️ exact set: `=45s`, `=perm`",
                                  parse_mode='Markdown', reply_markup=BACK_KB)
    elif d.startswith('admop_'):
        if not is_owner(uid): return
        try:
            body = d.replace('admop_', ''); t_s, op = body.rsplit('_', 1); target = int(t_s)
        except Exception:
            await q.edit_message_text("❌ Parse error", reply_markup=BACK_KB); return
        now = datetime.now()
        if op == 'perm': await apply_admin_time(target, '=', None, q=q)
        elif op == '0':
            a = get_admin(target)
            if a:
                a['expires_at'] = now.isoformat(); a['updated_at'] = now.isoformat(); replace_admin(target, a)
            await q.edit_message_text(f"⛔ Admin expired: {admin_label(target)}", reply_markup=BACK_KB)
        else:
            amt = int(op.replace('+', '').replace('-', '')); o = '+' if op.startswith('+') else '-'
            await apply_admin_time(target, o, now + timedelta(days=amt), q=q)
    elif d.startswith('del_admin_'):
        if not is_owner(uid): return
        tt = int(d.replace('del_admin_', ''))
        lbl = admin_label(tt)
        save_admins([a for a in load_admins() if a['user_id'] != tt]); stop_accounts_of(tt)
        await q.edit_message_text(f"🗑️ Admin deleted: {lbl}\n(accounts stopped)", reply_markup=BACK_KB)
    elif d == 'phone_login':
        c.user_data['awaiting'] = 'phone_number'
        await q.edit_message_text("📱 *Phone Login*\nSend number (with country code).\nIndia: `+91XXXXXXXXXX`",
                                  parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'add_account':
        c.user_data['awaiting'] = 'add_account'
        await q.edit_message_text("🔑 *Session Login*\nPaste your session string:", parse_mode='Markdown', reply_markup=BACK_KB)
    elif d == 'delete_account':
        accs = get_all_accounts(uid)
        if not accs: await q.edit_message_text("❌ No accounts", reply_markup=BACK_KB); return
        kb = [[InlineKeyboardButton(f"{'💚' if a.get('type')=='env' else '📱' if a.get('type')=='phone_auth' else '💙'} #{i} · {get_display_name(a)[:20]}",
                                    callback_data=f'del_acc_{a["id"]}')] for i, a in enumerate(accs, 1)]
        kb += [[InlineKeyboardButton("🗑️ Delete ALL", callback_data='del_all_accounts'),
                InlineKeyboardButton("🔙 Back", callback_data='back_main')]]
        await q.edit_message_text("Delete which?", reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'del_all_accounts':
        dd = [a for a in get_all_accounts(uid) if a.get('type') != 'env']
        kb = [[InlineKeyboardButton("☠️ YES Delete All", callback_data='del_all_confirm'),
               InlineKeyboardButton("Cancel", callback_data='delete_account')]]
        await q.edit_message_text(f"⚠️ Delete {len(dd)} accounts?", reply_markup=InlineKeyboardMarkup(kb))
    elif d == 'del_all_confirm':
        n = 0
        for a in get_all_accounts(uid):
            if a.get('type') == 'env': continue
            stop_account(a['id']); remove_account_by_id(a['id']); await disconnect_client(a['id'])
            set_special_msg(a['id'], ""); n += 1
        await q.edit_message_text(f"🗑️ Deleted {n}", reply_markup=BACK_KB)
    elif d.startswith('del_acc_'):
        acc_id = d.replace('del_acc_', '')
        t = next((a for a in get_all_accounts(uid) if a['id'] == acc_id), None)
        if not t: await q.edit_message_text("⛔ invalid", reply_markup=BACK_KB); return
        nm = get_display_name(t)
        if account_stats.get(acc_id, {}).get('running', False): stop_account(acc_id); await asyncio.sleep(1)
        remove_account_by_id(acc_id); await disconnect_client(acc_id); set_special_msg(acc_id, "")
        for dd in (account_stats, stop_flags, running_tasks, display_names, account_clients): dd.pop(acc_id, None)
        await q.edit_message_text(f"🗑️ Deleted: {nm}", reply_markup=BACK_KB)
    elif d == 'back_main':
        c.user_data['awaiting'] = None; c.user_data.pop('login_id', None)
        refresh_account_stats(uid); preload_display_names(get_all_accounts(uid))
        await q.edit_message_text(main_menu_text(uid), parse_mode='Markdown', reply_markup=main_menu_keyboard(uid))

# ---------------- photo handler ----------------
async def handle_photo(u, c):
    uid = u.effective_user.id; eu = u.effective_user
    record_user_info(uid, eu.first_name, eu.last_name, eu.username)
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
    if c.user_data.get('awaiting') == 'qr_set' and is_owner(uid) and u.message.photo:
        qr = load_qr(); qr['photo'] = u.message.photo[-1].file_id; save_qr(qr)
        c.user_data['awaiting'] = None
        await u.message.reply_text("✅ QR saved!", reply_markup=BACK_KB); return
    if not (is_owner(uid) or is_valid_admin(uid)): return
    if c.user_data.get('awaiting') == 'def_add_photo':
        cfg = get_default_profile(); ph = cfg.get('photos', []); ph.append(u.message.photo[-1].file_id)
        cfg['photos'] = ph; save_default_profile(cfg); c.user_data['awaiting'] = None
        await u.message.reply_text(f"🖼️ Logo #{len(ph)} saved", reply_markup=BACK_KB); return
    if c.user_data.get('awaiting') == 'broadcast_capture' and is_owner(uid):
        c.user_data['awaiting'] = None
        tid = c.user_data.pop('bc_uid', None)
        if tid is None:
            await u.message.reply_text("❌ Target lost — abar 👤 To One User theke shuru koro.", reply_markup=BACK_KB); return
        if u.message.video:
            await do_broadcast(u.message, c.bot, uid, u.message.caption or "", u.message.video.file_id, 'video', only_user_id=tid)
        elif u.message.photo:
            await do_broadcast(u.message, c.bot, uid, u.message.caption or "", u.message.photo[-1].file_id, 'photo', only_user_id=tid)
        elif u.message.animation:
            await do_broadcast(u.message, c.bot, uid, u.message.caption or "", u.message.animation.file_id, 'animation', only_user_id=tid)

# ---------------- text handler ----------------
async def handle_text(u, c):
    uid = u.effective_user.id; eu = u.effective_user
    record_user_info(uid, eu.first_name, eu.last_name, eu.username)
    text = u.message.text.strip(); aw = c.user_data.get('awaiting')
    FREE_STATES = ('pay_screenshot',)
    if not (is_owner(uid) or is_valid_admin(uid)) and aw not in FREE_STATES: return

    if aw == 'broadcast_target' and is_owner(uid):
        if text.lower() == '/cancel':
            c.user_data['awaiting'] = None; c.user_data.pop('bc_uid', None)
            await u.message.reply_text("❌ Cancelled.", reply_markup=BACK_KB); return
        try: tid = int(text.strip())
        except Exception:
            await u.message.reply_text("❌ Send USER_ID (only number):", reply_markup=BACK_KB); return
        c.user_data['bc_uid'] = tid; c.user_data['awaiting'] = 'broadcast_capture'
        await u.message.reply_text(f"✅ Target set: `{tid}`\nNow send text / photo / video.",
                                   parse_mode='Markdown', reply_markup=BACK_KB); return
    if aw == 'broadcast_capture' and is_owner(uid):
        c.user_data['awaiting'] = None
        tid = c.user_data.pop('bc_uid', None)
        if tid is None:
            await u.message.reply_text("❌ Target lost — Admin Panel → Broadcast → 👤 To One User theke abar shuru koro.", reply_markup=BACK_KB); return
        await do_broadcast(u.message, c.bot, uid, text, only_user_id=tid)
        return
    if aw == 'pay_screenshot':
        c.user_data['awaiting'] = None
        await u.message.reply_text("📸 Please send a PHOTO (screenshot), not text.", reply_markup=expired_panel_keyboard()); return
    if aw == 'plan_add' and is_owner(uid):
        c.user_data['awaiting'] = None
        parts = [x.strip() for x in text.split('|')]
        if len(parts) != 4:
            await u.message.reply_text("❌ Format: `Button | Name | Price | Days`", parse_mode='Markdown', reply_markup=BACK_KB); return
        plans = load_plans()
        plans.append({'plan_id': uuid.uuid4().hex[:6], 'btn_name': parts[0], 'name': parts[1],
                      'price': float(parts[2]), 'days': int(parts[3])})
        save_plans(plans)
        await u.message.reply_text("✅ Plan added!", reply_markup=BACK_KB); return
    if aw == 'adm_custom_time':
        c.user_data['awaiting'] = None
        if not is_owner(uid): return
        t = c.user_data.pop('adm_target', None)
        if not t:
            await u.message.reply_text("❌ Session reset. Try again.", reply_markup=BACK_KB); return
        minus = text.startswith('-')
        try: nd = parse_duration(text.lstrip('+-'))
        except Exception:
            await u.message.reply_text("❌ e.g. `+30m`, `-30m`, `=45s`, `1d 5h`", parse_mode='Markdown', reply_markup=BACK_KB); return
        await apply_admin_time(t, '-' if minus else '+', nd, text_ui=u.message)
        return
    if aw == 'spec_set_msg':
        c.user_data['awaiting'] = None
        aid = c.user_data.pop('spec_aid', None)
        if not aid or aid not in [a['id'] for a in get_all_accounts(uid)]:
            await u.message.reply_text("❌ reset, try again", reply_markup=BACK_KB); return
        set_special_msg(aid, text)
        await u.message.reply_text(f"✅ Special message pinned to {get_display_name_by_id(aid)}.", reply_markup=BACK_KB); return
    if aw == 'add_admin':
        c.user_data['awaiting'] = None
        if not is_owner(uid): return
        try: target, op, nd = parse_admin_cmd(text)
        except Exception:
            await u.message.reply_text("❌ Format: `USER_ID [+|-|=]TIME`\ne.g. `111 +2d 5h 30m`, `333 =perm`",
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
        c.user_data['awaiting'] = None; cfg = get_default_profile(); nm = cfg.get('names', [])
        nn = [x.strip() for x in text.split('\n') if x.strip()]; nm.extend(nn); cfg['names'] = nm; save_default_profile(cfg)
        await u.message.reply_text(f"✅ Added {len(nn)} (total {len(nm)})", reply_markup=BACK_KB); return
    if aw == 'def_bio':
        c.user_data['awaiting'] = None; cfg = get_default_profile(); cfg['bio'] = text; save_default_profile(cfg)
        await u.message.reply_text("✅ Bio saved", reply_markup=BACK_KB); return
    if aw == 'def_chan':
        c.user_data['awaiting'] = None; cfg = get_default_profile()
        cfg['channels'] = [x.strip() for x in re.split(r'[\n,]+', text) if x.strip()]; save_default_profile(cfg)
        await u.message.reply_text("✅ Links saved", reply_markup=BACK_KB); return
    if aw == 'add_message':
        c.user_data['awaiting'] = None; m = load_messages_for(uid); m.append(text); save_messages_for(uid, m)
        await u.message.reply_text(f"✅ Added, total {len(m)}", reply_markup=BACK_KB); return
    if aw in ('set_min', 'set_max', 'set_cycle'):
        c.user_data['awaiting'] = None
        mn, mx, cyc = speed_for(uid)
        try: v = int(text.strip())
        except Exception:
            await u.message.reply_text("❌ Number pathao.", reply_markup=BACK_KB); return
        if aw == 'set_min':
            if v >= mx: await u.message.reply_text(f"❌ Min must be < Max ({mx})", reply_markup=BACK_KB); return
            set_speed(uid, min_i=v)
        elif aw == 'set_max':
            if v <= mn: await u.message.reply_text(f"❌ Max must be > Min ({mn})", reply_markup=BACK_KB); return
            set_speed(uid, max_i=v)
        else:
            if v < 5: await u.message.reply_text("❌ Cycle >= 5", reply_markup=BACK_KB); return
            set_speed(uid, cycle=v)
        await u.message.reply_text(f"✅ Speed updated: {speed_for(uid)}", reply_markup=BACK_KB); return

    # =============== PHONE LOGIN (MARKDOWN-SAFE: plain text only) ===============
    if aw == 'phone_number':
        c.user_data['awaiting'] = None
        try:
            ph = text.strip()
            if not ph.startswith('+'): ph = '+' + ph
            if not re.match(r'^\+\d{7,15}$', ph):
                await u.message.reply_text("❌ Invalid! Example +91XXXXXXXXXX", reply_markup=BACK_KB); return
            reached, rm = account_limit_reached(uid)
            if reached: await u.message.reply_text(rm, reply_markup=BACK_KB); return
            if not API_ID_1 or not API_HASH_1:
                await u.message.reply_text("❌ API keys missing on server!", reply_markup=BACK_KB); return
            for k in [k for k, v in phone_login_states.items() if v.get('owner_id') == uid]:
                old = phone_login_states.pop(k, None)
                if old and old.get('client'):
                    try: await old['client'].disconnect()
                    except Exception: pass
            sm = await u.message.reply_text("⏳ Sending OTP...", reply_markup=BACK_KB)
            client = None
            try:
                client = TelegramClient(StringSession(), API_ID_1, API_HASH_1, receive_updates=False)
                await client.connect(); sent = await client.send_code_request(ph)
                lid = gen_unique_id("plogin", uid)
                phone_login_states[lid] = {'phone': ph, 'owner_id': uid, 'client': client,
                                           'phone_code_hash': sent.phone_code_hash, 'tries': 0}
                c.user_data['awaiting'] = 'otp_code'; c.user_data['login_id'] = lid
                # PLAIN TEXT (no Markdown) so input can't break entity parsing
                try:
                    await sm.edit_text(f"✉️ OTP sent to {ph}\n\nTelegram app e code ashbe. "
                                       f"Code expire hole abar Phone Login chapo.", reply_markup=BACK_KB)
                except Exception: pass
            except Exception as e:
                if client:
                    try: await client.disconnect()
                    except Exception: pass
                await sm.edit_text(f"❌ {str(e)[:150]}", reply_markup=BACK_KB)
        except Exception as e:
            await u.message.reply_text(f"❌ {str(e)[:120]}", reply_markup=BACK_KB)
        return

    # OTP code
    if aw == 'otp_code':
        c.user_data['awaiting'] = None
        lid = c.user_data.pop('login_id', None)
        st = phone_login_states.get(lid)
        if not st or not st.get('client'):
            await u.message.reply_text("❌ Login session lost. Abar Phone Login chapo.", reply_markup=BACK_KB); return
        code = re.sub(r'\D', '', text)
        try:
            await st['client'].sign_in(phone=st['phone'], code=code, phone_code_hash=st['phone_code_hash'])
        except SessionPasswordNeededError:
            c.user_data['awaiting'] = 'two_fa'; c.user_data['login_id'] = lid; st['tries'] += 1
            await u.message.reply_text("🔒 2FA password pathao:", reply_markup=BACK_KB); return
        except PhoneCodeExpiredError:
            try: await st['client'].disconnect()
            except Exception: pass
            phone_login_states.pop(lid, None)
            await u.message.reply_text("⌛ Code EXPIRED. Abar Phone Login → number pathao.", reply_markup=BACK_KB); return
        except PhoneCodeInvalidError:
            st['tries'] += 1
            if st['tries'] >= 3:
                try: await st['client'].disconnect()
                except Exception: pass
                phone_login_states.pop(lid, None)
                await u.message.reply_text("❌ 3 bar bhul. Abar Phone Login.", reply_markup=BACK_KB); return
            c.user_data['awaiting'] = 'otp_code'; c.user_data['login_id'] = lid
            await u.message.reply_text(f"❌ Bhul code ({st['tries']}/3):", reply_markup=BACK_KB); return
        except Exception as e:
            try: await st['client'].disconnect()
            except Exception: pass
            phone_login_states.pop(lid, None)
            await u.message.reply_text(f"❌ {str(e)[:150]}", reply_markup=BACK_KB); return
        s = st['client'].session.save(); ph = st['phone']
        try: await st['client'].disconnect()
        except Exception: pass
        phone_login_states.pop(lid, None)
        await finish_phone_login(u, c, uid, ph, s)
        return

    # 2FA password
    if aw == 'two_fa':
        c.user_data['awaiting'] = None
        lid = c.user_data.pop('login_id', None)
        st = phone_login_states.get(lid)
        if not st or not st.get('client'):
            await u.message.reply_text("❌ Session lost. Abar Phone Login.", reply_markup=BACK_KB); return
        try:
            await st['client'].sign_in(password=text)
        except Exception as e:
            c.user_data['awaiting'] = 'two_fa'; c.user_data['login_id'] = lid
            await u.message.reply_text(f"❌ Bhul password. Abar try:\n{str(e)[:100]}", reply_markup=BACK_KB); return
        s = st['client'].session.save(); ph = st['phone']
        try: await st['client'].disconnect()
        except Exception: pass
        phone_login_states.pop(lid, None)
        await finish_phone_login(u, c, uid, ph, s)
        return

    # Session string login
    if aw == 'add_account':
        c.user_data['awaiting'] = None
        try:
            reached, rm = account_limit_reached(uid)
            if reached: await u.message.reply_text(rm, reply_markup=BACK_KB); return
            await u.message.reply_text("⏳ Validating session...", reply_markup=BACK_KB)
            if not API_ID_1 or not API_HASH_1:
                await u.message.reply_text("❌ API keys missing!", reply_markup=BACK_KB); return
            tmp = TelegramClient(StringSession(text.strip()), API_ID_1, API_HASH_1, receive_updates=False)
            await tmp.start(); me = await tmp.get_me(); sstr = tmp.session.save(); await tmp.disconnect()
            ok, nid = add_dynamic_account(human_name(me), sstr, uid)
            if not ok: await u.message.reply_text("❌ Already exists", reply_markup=BACK_KB); return
            save_names(); refresh_account_stats(uid)
            await u.message.reply_text(f"✅ Account added: {human_name(me)}", reply_markup=BACK_KB)
        except AuthKeyUnregisteredError:
            await u.message.reply_text("❌ Session invalid/expired.", reply_markup=BACK_KB)
        except Exception as e:
            await u.message.reply_text(f"❌ {str(e)[:150]}", reply_markup=BACK_KB)
        return
    if is_owner(uid) or is_valid_admin(uid):
        await u.message.reply_text("Menu theke option bacho 👆", reply_markup=main_menu_keyboard(uid))

# =============== PHONE LOGIN SUCCESS (plain text, no Markdown) ===============
async def finish_phone_login(u, c, uid, ph, session_str):
    try:
        reached, rm = account_limit_reached(uid)
        if reached:
            await u.message.reply_text(rm, reply_markup=BACK_KB); return
        if not API_ID_1 or not API_HASH_1:
            await u.message.reply_text("❌ API keys missing!", reply_markup=BACK_KB); return
        tmp = TelegramClient(StringSession(session_str), API_ID_1, API_HASH_1, receive_updates=False)
        await tmp.start(); me = await tmp.get_me(); name = human_name(me)
        sstr2 = tmp.session.save(); await tmp.disconnect()
        nid = add_phone_auth_account(name, sstr2, uid, ph)
        refresh_account_stats(uid)
        # plain text - no Markdown so names/symbols can't break parsing
        await u.message.reply_text(f"✅ Logged in: {name} ({ph})", reply_markup=BACK_KB)
    except Exception as e:
        await u.message.reply_text(f"❌ {str(e)[:150]}", reply_markup=BACK_KB)

# ---------------- data persistence ----------------
def load_data():
    global MESSAGE, MIN_INTERVAL, MAX_INTERVAL, CYCLE_WAIT, SHOW_START_TO_OTHERS
    d = load_json(data_file, {})
    MESSAGE = d.get('message', MESSAGE)
    MIN_INTERVAL = d.get('min_interval', MIN_INTERVAL)
    MAX_INTERVAL = d.get('max_interval', MAX_INTERVAL)
    CYCLE_WAIT = d.get('cycle_wait', CYCLE_WAIT)
    SHOW_START_TO_OTHERS = d.get('show_start_to_others', SHOW_START_TO_OTHERS)
def save_data():
    save_json(data_file, {'message': MESSAGE, 'min_interval': MIN_INTERVAL,
                          'max_interval': MAX_INTERVAL, 'cycle_wait': CYCLE_WAIT,
                          'show_start_to_others': SHOW_START_TO_OTHERS})

# ---------------- flask keepalive ----------------
flask_app = Flask(__name__)
@flask_app.route('/')
def _home(): return "Bot alive ✅"
@flask_app.route('/health')
def _health(): return "OK", 200
def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)),
                  debug=False, use_reloader=False)
def start_flask():
    threading.Thread(target=run_flask, daemon=True).start()

async def on_error(u, c):
    logger.error(f"Update error: {u.error}", exc_info=u.error)

# ---------------- main ----------------
async def main():
    load_data()
    if not BOT_TOKEN or not OWNER_ID:
        logger.critical("BOT_TOKEN / OWNER_ID missing! Add env vars."); return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(on_error)
    await init_env_accounts()
    asyncio.create_task(admin_expiry_checker())
    logger.info("Bot starting (polling)...")
    await app.initialize(); await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot v1.1 running")
    await asyncio.Event().wait()

if __name__ == '__main__':
    start_flask()
    asyncio.run(main())
