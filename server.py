import sqlite3, secrets, hashlib, hmac, json, csv, io, os, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from datetime import date
from decimal import Decimal, InvalidOperation
ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('FINTRACK_DB', str(ROOT/'finance.sqlite3')))
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def password(p,s): return hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),310000).hex()
def init():
 with db() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user'); CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), expires INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS ops(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),day TEXT NOT NULL,kind TEXT CHECK(kind IN ('income','expense')),category TEXT NOT NULL,amount INTEGER CHECK(amount>0),note TEXT NOT NULL); CREATE INDEX IF NOT EXISTS ops_owner_day ON ops(user_id,day);''')
  if not c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
   s=secrets.token_hex(16); c.execute('INSERT INTO users(login,salt,hash,role) VALUES(?,?,?,?)',('demo',s,password('Demo2026!',s),'admin'))
   uid=c.execute('SELECT id FROM users WHERE login=?',('demo',)).fetchone()[0]
   today=date.today().isoformat()
   c.executemany('INSERT INTO ops(user_id,day,kind,category,amount,note) VALUES(?,?,?,?,?,?)',[(uid,today,'income','Продажи',12500000,'Демонстрационная операция'),(uid,today,'expense','Аренда',3500000,'Демонстрационная операция'),(uid,today,'expense','Маркетинг',1500000,'Демонстрационная операция')])
class Handler(BaseHTTPRequestHandler):
 def send(self,status,data,typ='application/json; charset=utf-8',cookie=None):
  if isinstance(data, (dict,list)): data=json.dumps(data,ensure_ascii=False).encode()
  elif isinstance(data,str): data=data.encode()
  self.send_response(status); self.send_header('Content-Type',typ); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
  if cookie: self.send_header('Set-Cookie',cookie)
  self.end_headers(); self.wfile.write(data)
 def token(self):
  try: return SimpleCookie(self.headers.get('Cookie',''))['session'].value
  except (KeyError,ValueError): return ''
 def body(self):
  n=int(self.headers.get('Content-Length',0));
  if n>65536: raise ValueError('Слишком большой запрос')
  return json.loads(self.rfile.read(n) or b'{}')
 def do_GET(self): self.handle_api()
 def do_POST(self): self.handle_api()
 def do_PUT(self): self.handle_api()
 def do_DELETE(self): self.handle_api()
 def handle_api(self):
  from urllib.parse import urlparse,parse_qs
  import time
  p=urlparse(self.path); path=p.path; method=self.command
  try:
   if path=='/' and method=='GET': return self.send(200,(ROOT/'index.html').read_bytes(),'text/html; charset=utf-8')
   if method!='GET' and self.headers.get('Origin') and self.headers['Origin'] not in ('http://'+self.headers.get('Host',''),'https://'+self.headers.get('Host','')): return self.send(403,{'error':'Недопустимый источник запроса'})
   with db() as c:
    if path in ('/api/login','/api/register') and method=='POST':
     b=self.body(); login=str(b.get('login','')).strip(); pw=str(b.get('password',''))
     if path.endswith('register'):
      if not re.fullmatch(r'[A-Za-z0-9_]{3,32}',login) or not 8<=len(pw)<=128: raise ValueError('Логин: 3–32 латинских символа, пароль: 8–128 символов')
      s=secrets.token_hex(16); c.execute('INSERT INTO users(login,salt,hash) VALUES(?,?,?)',(login,s,password(pw,s)))
     u=c.execute('SELECT * FROM users WHERE login=?',(login,)).fetchone()
     if not u or len(pw)>128 or not hmac.compare_digest(u['hash'],password(pw,u['salt'])): return self.send(401,{'error':'Неверный логин или пароль'})
     token=secrets.token_urlsafe(32); c.execute('INSERT INTO sessions VALUES(?,?,?)',(token,u['id'],int(time.time())+86400)); return self.send(200,{'login':u['login'],'role':u['role']},cookie=f'session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400')
    u=c.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>?',(self.token(),int(time.time()))).fetchone()
    if not u: return self.send(401,{'error':'Войдите в систему'})
    uid=u['id']
    if path=='/api/logout' and method=='POST': c.execute('DELETE FROM sessions WHERE token=?',(self.token(),)); return self.send(200,{},cookie='session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict')
    if path=='/api/me': return self.send(200,{'login':u['login'],'role':u['role']})
    if path=='/api/users' and method=='GET':
     if u['role']!='admin': return self.send(403,{'error':'Недостаточно прав'})
     return self.send(200,[dict(r) for r in c.execute('SELECT id,login,role FROM users ORDER BY id')])
    if path in ('/api/ops','/api/export') and method=='GET':
     q=parse_qs(p.query); sql='SELECT id,day,kind,category,amount,note FROM ops WHERE user_id=?'; args=[uid]
     for key,op in [('start','>='),('end','<=')]:
      if q.get(key): sql+=f' AND day {op} ?'; args.append(date.fromisoformat(q[key][0]).isoformat())
     if q.get('kind') and q['kind'][0] in ('income','expense'): sql+=' AND kind=?'; args.append(q['kind'][0])
     rows=[dict(r) for r in c.execute(sql+' ORDER BY day DESC,id DESC',args)]
     if path.endswith('export'):
      out=io.StringIO(); w=csv.writer(out,delimiter=';'); w.writerow(['Дата','Тип','Категория','Сумма, руб.','Комментарий'])
      safe=lambda s: "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s
      for r in rows: w.writerow([r['day'],'Доход' if r['kind']=='income' else 'Расход',safe(r['category']),f"{r['amount']/100:.2f}",safe(r['note'])])
      return self.send(200,('\ufeff'+out.getvalue()).encode(),'text/csv; charset=utf-8')
     return self.send(200,rows)
    match=re.fullmatch(r'/api/ops(?:/(\d+))?',path)
    if match:
     oid=match.group(1)
     if method=='DELETE' and oid:
      n=c.execute('DELETE FROM ops WHERE id=? AND user_id=?',(oid,uid)).rowcount; return self.send(200 if n else 404,{} if n else {'error':'Операция не найдена'})
     if (method=='POST' and not oid) or (method=='PUT' and oid):
      b=self.body(); day=date.fromisoformat(b['day']).isoformat(); kind=b['kind']; cat=str(b['category']).strip(); note=str(b.get('note','')).strip(); amount=Decimal(str(b['amount']))
      if not amount.is_finite() or amount<=0 or amount>Decimal('1000000000') or amount*100!=(amount*100).to_integral_value() or kind not in ('income','expense') or not 1<=len(cat)<=80 or len(note)>300: raise ValueError('Проверьте сумму, категорию и комментарий')
      vals=(day,kind,cat,int(amount*100),note)
      if oid:
       n=c.execute('UPDATE ops SET day=?,kind=?,category=?,amount=?,note=? WHERE id=? AND user_id=?',(*vals,oid,uid)).rowcount; return self.send(200 if n else 404,{} if n else {'error':'Операция не найдена'})
      cur=c.execute('INSERT INTO ops(day,kind,category,amount,note,user_id) VALUES(?,?,?,?,?,?)',(*vals,uid)); return self.send(201,{'id':cur.lastrowid})
    return self.send(404,{'error':'Не найдено'})
  except sqlite3.IntegrityError: return self.send(409,{'error':'Логин уже занят или данные некорректны'})
  except (ValueError,KeyError,TypeError,InvalidOperation): return self.send(400,{'error':'Проверьте введённые данные'})
if __name__=='__main__':
 init(); port=int(os.environ.get('PORT','8000')); print(f'FinTrack: http://127.0.0.1:{port}',flush=True); ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
