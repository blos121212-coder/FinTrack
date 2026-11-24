import unittest, tempfile, threading, urllib.request, urllib.error, json, http.cookiejar
from pathlib import Path
import server
from http.cookiejar import CookieJar
class TestAPI(unittest.TestCase):
 def test_workflow(self):
  with tempfile.TemporaryDirectory() as d:
   server.DB=Path(d)/'test.db'; server.init(); http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler); t=threading.Thread(target=http.serve_forever,daemon=True); t.start(); base=f'http://127.0.0.1:{http.server_port}'
   def client(): return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
   a=client(); b=client()
   def req(c,path,method='GET',data=None):
    try:
     with c.open(urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method)) as r: return r.status,r.read()
    except urllib.error.HTTPError as e: return e.code,e.read()
   try:
    self.assertEqual(req(a,'/')[0],200); self.assertEqual(req(a,'/api/ops')[0],401)
    self.assertEqual(req(a,'/api/login','POST',{'login':'demo','password':'wrong'})[0],401)
    self.assertEqual(req(a,'/api/login','POST',{'login':'demo','password':'Demo2026!'})[0],200)
    self.assertEqual(len(json.loads(req(a,'/api/ops')[1])),3); self.assertEqual(req(a,'/api/users')[0],200)
    data={'day':'2026-11-24','kind':'income','category':'Тест','amount':'123.45','note':'test'}
    status,body=req(a,'/api/ops','POST',data); self.assertEqual(status,201); oid=json.loads(body)['id']; path=f'/api/ops/{oid}'
    data['amount']='200.12'; self.assertEqual(req(a,path,'PUT',data)[0],200)
    self.assertTrue(any(x['amount']==20012 for x in json.loads(req(a,'/api/ops?kind=income')[1])))
    self.assertEqual(req(a,'/api/export')[0],200)
    self.assertEqual(req(b,'/api/register','POST',{'login':'other','password':'Other123!'})[0],200)
    self.assertEqual(json.loads(req(b,'/api/ops')[1]),[]); self.assertEqual(req(b,'/api/users')[0],403); self.assertEqual(req(b,path,'DELETE')[0],404)
    self.assertEqual(req(a,path,'DELETE')[0],200); self.assertEqual(req(a,'/api/logout','POST')[0],200); self.assertEqual(req(a,'/api/ops')[0],401)
   finally: http.shutdown(); http.server_close(); t.join()
if __name__=='__main__': unittest.main()
