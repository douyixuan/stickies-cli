#!/usr/bin/env python3
"""Schedule first creation only; never update existing Stickies. Never drive UI or alter trust."""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

MARKER = 'CODEX_STICKIES_V1'
ROOT = Path(__file__).resolve().parent
STATE = Path.home() / '.local/state/codex-stickies-hook/state.sqlite3'
CLAUDE_HOST = re.compile(r'^local_[A-Za-z0-9-]{1,64}$')
# Stop repeated unavailable attempts; never use a foreground fallback.
ATTEMPTS = 3

def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=2)
    os.chmod(path, 0o600)
    db.execute('CREATE TABLE IF NOT EXISTS turns (session TEXT, token TEXT, status TEXT, updated REAL, PRIMARY KEY(session,token))')
    db.execute('CREATE TABLE IF NOT EXISTS desktop_lease (id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT, expires REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS created (session TEXT PRIMARY KEY)')
    db.execute("INSERT OR IGNORE INTO created SELECT DISTINCT session FROM turns WHERE status IN ('synced','unchanged','created','exists')")
    db.commit()  # Finish schema/backfill before callers start an explicit transaction.
    return db

def allowed(session, home):
    files = sorted(home.glob('state_*.sqlite'), reverse=True)
    if not files:
        return False
    try:
        with sqlite3.connect(files[0].as_uri()+'?mode=ro', uri=True, timeout=1) as db:
            row = db.execute('SELECT source,archived FROM threads WHERE id=?',(session,)).fetchone()
        return bool(row and not row[1] and row[0] != 'exec' and 'subagent' not in row[0])
    except sqlite3.Error:
        return False

def claude_entry(env):
    """Desktop deep link for an attended Claude session; None when the session has no verified link."""
    host = env.get('CLAUDE_CODE_HOST_SESSION_ID', '')
    if not CLAUDE_HOST.match(host) or env.get('CLAUDE_CODE_SESSION_ATTENDED', '1') != '1':
        return None
    return 'claude://code/continue?session=' + host

def handle(event, state=STATE, home=None, agent='codex', env=None):
    if not isinstance(event,dict) or event.get('agent_id') or event.get('agent_type'):
        return {}
    if event.get('hook_event_name') != 'UserPromptSubmit' or event.get('stop_hook_active'):
        return {}
    session = str(uuid.UUID(event['session_id']))
    if agent == 'claude':
        entry = claude_entry(os.environ if env is None else env)
        if not entry:
            return {}
    else:
        if not allowed(session,home or Path.home()/'.codex'):
            return {}
        entry = f'codex://threads/{session}'
    body = event.get('prompt','')
    if not isinstance(body,str) or not body.strip() or MARKER in body or body.strip() in ('HEARTBEAT_OK','NO_REPLY'):
        return {}
    token = str(event.get('turn_id') or uuid.uuid4())
    with connect(state) as db:
        if db.execute('SELECT 1 FROM created WHERE session=?',(session,)).fetchone():
            return {}
        if db.execute("SELECT count(*) FROM turns WHERE session=? AND status='unavailable'",(session,)).fetchone()[0] >= ATTEMPTS:
            return {}
        db.execute('DELETE FROM turns WHERE updated < ?', (time.time()-30*86400,))
        cur = db.execute('INSERT OR IGNORE INTO turns VALUES (?,?,?,?)',(session,token,'pending',time.time()))
        if not cur.rowcount:
            return {}
    receipt = json.dumps({'session':session,'token':token},ensure_ascii=False)
    option = f" --url '{entry}' --label '返回 Claude 任务'" if agent == 'claude' else ''
    task = (f'[{MARKER}] 便笺规则版本 background-create-v3。当前任务还没有便笺。'
            '日常自动创建仅运行下面的命令，标题写「熟悉的项目名｜任务名」，其余两项各一句话：'
            f"/usr/bin/python3 {ROOT}/create_note.py --receipt '{receipt}' --title '<标题>' --progress '<进展>' --next-step '<下一步>'{option}。"
            '日常路径已接入 stk 后台创建，已有便笺只读去重；新贴通过焦点和剪贴板检测、原贴保护及本机窗口链接回读后才记录 created。返回 unavailable 或 pending 时不重试、不换工具，不声称真实创建。'
            '例外：用户已明确授权便笺工具真实验证时，允许用 stk 离线创建一张本任务新便笺，按授权退出并后台重启 Stickies，读取窗口并验证新便笺链接；既有授权跨轮有效，不重复询问。'
            '验证必须不抢键盘焦点、不用前台粘贴、不切 Space、不改变已有便笺正文、链接、位置、样式；先备份并记录已有便笺，再比较验收。'
            '链接点击若会改变当前焦点，不擅自执行，记录该项未通过。只有新便笺显示、链接可点击、焦点保护和旧便笺保护均验证通过后，才接入自动 hook。'
            f'任务入口 {entry}。细则见 {ROOT}/rules.md。')
    return {'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':task}}

def owner(data):
    return str(uuid.UUID(data['session']))+':'+str(data['token'])

def acquire(data, state=None):
    """Take the 120-second desktop lease unless another turn holds it."""
    with connect(state or STATE) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT owner,expires FROM desktop_lease WHERE id=1').fetchone()
        if row and row[0]!=owner(data) and row[1]>time.time():
            return False
        db.execute('INSERT OR REPLACE INTO desktop_lease VALUES (1,?,?)',(owner(data),time.time()+120))
    return True

def record(data, status, state=None):
    """Store the turn's result and release its lease."""
    session=str(uuid.UUID(data['session']))
    with connect(state or STATE) as db:
        db.execute('INSERT OR REPLACE INTO turns VALUES (?,?,?,?)',(session,str(data['token']),status,time.time()))
        if status in ('created','exists','synced','unchanged'):
            db.execute('INSERT OR IGNORE INTO created VALUES (?)',(session,))
        db.execute('DELETE FROM desktop_lease WHERE owner=?',(owner(data),))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--receipt',help='JSON with session and token from hook context')
    parser.add_argument('--acquire', action='store_true', help='Acquire 120-second desktop lease; requires receipt')
    parser.add_argument('--status',choices=['created','exists','unavailable','synced','unchanged'])
    parser.add_argument('--agent',choices=['codex','claude'],default='codex',help='CLI that invoked the hook')
    args=parser.parse_args()
    try:
        if args.receipt:
            data=json.loads(args.receipt)
            if args.acquire:
                print(json.dumps({'acquired':True,'lease_seconds':120} if acquire(data) else {'acquired':False})); return
            if not args.status: raise ValueError('status required')
            record(data,args.status)
            print(json.dumps({'status':args.status})); return
        raw=sys.stdin.buffer.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError('oversized input')
        output=handle(json.loads(raw),agent=args.agent)
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):
        print('stickies-hook: skipped; input or local state unavailable',file=sys.stderr)
        output={}
    print(json.dumps(output,ensure_ascii=False))

if __name__=='__main__': main()
