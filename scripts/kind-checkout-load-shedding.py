#!/usr/bin/env python3
"""Explicit Kind-only bounded experiment; uses sandbox payments and preserves evidence."""
import importlib.util,json,os,subprocess,sys,time,threading,hashlib,uuid,yaml
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];os.umask(0o077)
s=importlib.util.spec_from_file_location('ha',ROOT/'scripts/kind-ha-experiment.py');h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
r=h.module(ROOT/'scripts/reliability-runner.py','rr');op=r.Operator(SimpleNamespace(context=h.CONTEXT,namespace='eurotransit'))
run='et-kind-shedding-'+uuid.uuid4().hex[:10];out=ROOT/'load-results'/run;out.mkdir();print('ARTIFACTS',out,flush=True)
pre=h.preflight(False);h.save(out/'preflight.json',pre);provider=h.secret('payments-provider-credentials','provider-api-key');assert provider.startswith(('sk_test_','rk_test_'))
op.cm('eurotransit-load-test-lock',{'runId':run,'mode':'kind-load-shedding','output':str(out)})
stop=threading.Event();observations=[];thread=None;enabled=False
meta={'runId':run,'mode':'kind-load-shedding','context':h.CONTEXT,'startedAt':h.now(),'maximumCheckouts':8,'gatewayLimit':{'average':1,'period':'1s','burst':1},'deploymentMethod':'direct Kind-only rendered ingress resources; not GitOps evidence'}
try:
 values=json.loads(h.command(['helm','get','values','eurotransit','--kube-context',h.CONTEXT,'-n','eurotransit','-a','-o','json']));h.save(out/'helm-values-before.json',values)
 def ingress(limited):
  rendered=h.command(['helm','template','eurotransit',str(ROOT/'charts/eurotransit'),'-n','eurotransit','-f',str(out/'helm-values-before.json'),'--set','ingress.checkoutRateLimit.enabled='+str(limited).lower(),'--set','ingress.checkoutRateLimit.average=1','--set','ingress.checkoutRateLimit.period=1s','--set','ingress.checkoutRateLimit.burst=1'])
  docs=[d for d in yaml.safe_load_all(rendered) if d and ((d['kind']=='IngressRoute' and d['metadata']['name']=='eurotransit-public-api') or (d['kind']=='Middleware' and d['metadata']['name'] in ('eurotransit-secure-headers','eurotransit-forward-auth','eurotransit-checkout-rate-limit')))]
  assert any(d['kind']=='IngressRoute' for d in docs)
  assert any(d['metadata']['name']=='eurotransit-checkout-rate-limit' for d in docs)==limited
  return yaml.safe_dump_all(docs)

 before=h.obj('ingressroute','eurotransit-public-api');h.save(out/'ingress-before.json',before)
 assert not any(any(m['name']=='eurotransit-checkout-rate-limit' for m in x.get('middlewares',[])) for x in before['spec']['routes'])
 choices=op.db('inventory_db',"SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT route_id,travel_date,seat_id FROM seats WHERE status='AVAILABLE' AND route_id='rt-to-mi-001' AND travel_date>=CURRENT_DATE+10 ORDER BY travel_date,seat_id LIMIT 300) t")
 claims=h.obj('configmap','-l','eurotransit.io/load-test=true')['items'];claimed={tuple(json.loads(c['data']['fixture'])) for c in claims if c.get('data',{}).get('fixture')}
 choices=[s for s in choices if (s['route_id'],s['travel_date'],s['seat_id']) not in claimed][:8];assert len(choices)==8
 offer=next(o for o in h.request(h.BASE+'/api/catalog/offers') if o['routeId']=='rt-to-mi-001' and o['offerId']=='of-001')
 fixtures=[{'routeId':s['route_id'],'offerId':offer['offerId'],'travelDate':s['travel_date'],'seatId':s['seat_id'],'unitPrice':offer['price'],'currency':offer['currency']} for s in choices]
 for f in fixtures:
  key=json.dumps([f['routeId'],f['travelDate'],f['seatId']]);op.cm('et-fixture-'+hashlib.sha256(key.encode()).hexdigest()[:24],{'fixture':key,'runId':run})
 h.save(out/'fixtures.json',{'version':1,'fixtures':fixtures});auth=h.token()
 for _ in range(3):h.request(h.BASE+'/api/orders/seat-availability?routeId='+fixtures[0]['routeId']+'&travelDate='+fixtures[0]['travelDate'],token=auth)
 previous=op.db('orders_db',"SELECT to_json(id::text) FROM orders WHERE status='CONFIRMED' ORDER BY created_at DESC LIMIT 1")
 def probe():
  while not stop.is_set():
   for kind,url in [('catalog',h.BASE+'/api/catalog/routes'),('order-poll',h.BASE+'/api/orders/'+previous)]:
    started=time.monotonic();code=0
    try:h.request(url,token=auth);code=200
    except Exception as e:code=getattr(e,'code',0)
    observations.append({'at':h.now(),'kind':kind,'httpStatus':code,'durationMs':round((time.monotonic()-started)*1000,2)})
   stop.wait(.2)
 op.snapshot(out,'before');h.save(out/'run.json',meta)
 manifest=ingress(True);(out/'ingress-enabled.yaml').write_text(manifest);h.k('apply','-f','-',data=manifest);enabled=True
 time.sleep(2);h.save(out/'rate-limit-live.json',h.obj('middleware','eurotransit-checkout-rate-limit'));h.save(out/'ingress-enabled.json',h.obj('ingressroute','eurotransit-public-api'))
 thread=threading.Thread(target=probe,daemon=True);thread.start()
 env=os.environ.copy();env.update(PUBLIC_URL=h.BASE,TOKEN_URL=h.ISSUER+'/protocol/openid-connect/token',CLIENT_ID='eurotransit-load-test',CLIENT_SECRET=h.secret('eurotransit-load-test-credentials','client-secret'),RUN_ID=run,SCENARIO='spike',MAX_ATTEMPTS='8',MAX_VUS='2',POLL_TIMEOUT_SECONDS='30',EXPECT_OVERLOAD='true',ALLOW_INSECURE_TLS='true',OUTPUT_DIR=str(out),FIXTURES_FILE=str(out/'fixtures.json'))
 with (out/'runner.log').open('w') as log:result=subprocess.run([sys.executable,str(ROOT/'load-tests/run.py')],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
 meta.update(finishedAt=h.now(),exitCode=result.returncode);h.save(out/'run.json',meta)
finally:
 stop.set()
 if thread:thread.join(timeout=15)
 h.save(out/'independent-probes.json',observations)
 if enabled:
  h.k('apply','-f','-',data=ingress(False));h.k('delete','middleware','eurotransit-checkout-rate-limit','--ignore-not-found');h.save(out/'ingress-restored.json',h.obj('ingressroute','eurotransit-public-api'))
 op.k('delete','configmap','eurotransit-load-test-lock')
# Preserve original acceptance evidence and audit accepted orders independently.
op.snapshot(out,'after');verified=h.collect(out,provider)
rows=[json.loads(l) for l in (out/'orders.jsonl').read_text().splitlines()]
refused=[x for x in rows if x['httpStatus']==429];keys=','.join("'"+x['idempotencyKey']+"'" for x in refused);assert refused
mapped=op.db('orders_db','SELECT count(*) FROM idempotency_keys WHERE key IN ('+keys+')');assert mapped==0
# Refused fixture tuples are exclusive and were available before traffic.
refusedSeats=[]
for row in refused:
 f=row['fixture'];status=op.db('inventory_db',"SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT status FROM seats WHERE route_id='"+f['routeId']+"' AND travel_date='"+f['travelDate']+"' AND seat_id='"+f['seatId']+"') t");refusedSeats.extend(status)
h.save(out/'refusal-audit.json',{'refusedCount':len(refused),'idempotencyRowsForRefusedKeys':mapped,'refusedSeatStates':refusedSeats})
traefik=h.command(['kubectl','--context',h.CONTEXT,'-n','traefik','logs','deployment/traefik','--since-time='+meta['startedAt']]);(out/'traefik-access.log').write_text(traefik)
summary={'runId':run,'context':h.CONTEXT,'originalClientVerified':verified,'harnessExitCode':result.returncode,'attempts':len(rows),'refused429':len(refused),'confirmed':sum(x['outcome']=='confirmed' for x in rows),'recoveryConfirmed':sum(x['phase']=='recovery' and x['outcome']=='confirmed' for x in rows),'refusedKeysAbsent':mapped==0,'refusedSeatsAvailable':all(x['status']=='AVAILABLE' for x in refusedSeats),'independentProbes':{kind:{'total':sum(x['kind']==kind for x in observations),'http200':sum(x['kind']==kind and x['httpStatus']==200 for x in observations)} for kind in ['catalog','order-poll']},'restoredDisabled':True}
h.save(out/'result.json',summary);print(json.dumps(summary,indent=2),flush=True)
