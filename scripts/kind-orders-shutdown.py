#!/usr/bin/env python3
"""Explicit Kind-only bounded experiment; uses sandbox payments and preserves evidence."""
import importlib.util,json,os,subprocess,sys,time,threading,re,signal,hashlib,uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('ha',ROOT/'scripts/kind-ha-experiment.py');h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
os.umask(0o077)
run_id='et-kind-shutdown-'+uuid.uuid4().hex[:10];out=ROOT/'load-results'/run_id;out.mkdir(mode=0o700);print('ARTIFACTS',out,flush=True)
pre=h.preflight(False);h.save(out/'preflight.json',pre)
provider=h.secret('payments-provider-credentials','provider-api-key');assert provider.startswith(('sk_test_','rk_test_'))
r=h.module(ROOT/'scripts/reliability-runner.py','runner');op=r.Operator(SimpleNamespace(context=h.CONTEXT,namespace='eurotransit'))
op.cm('eurotransit-load-test-lock',{'runId':run_id,'mode':'workstation','context':h.CONTEXT,'output':str(out)})
meta={'runId':run_id,'mode':'kind-orders-pod-shutdown','context':h.CONTEXT,'startedAt':h.now(),'barrierSeconds':18,'maximumCheckouts':4}
stop=threading.Event();events=[];observations=[];readiness=[];threads=[];logs={};streams=[];target=None;forward=process=barrier=None;handles=[]

def event(name,**kwargs):
 e=dict(at=h.now(),event=name,**kwargs);events.append(e);h.save(out/'timeline.json',events);print(json.dumps(e),flush=True)

def watch_target():
 while not stop.is_set():
  row={'at':h.now()}
  try:
   pod=h.obj('pod',target['metadata']['name']);row.update(deletionTimestamp=pod['metadata'].get('deletionTimestamp'),ready=any(c['type']=='Ready' and c['status']=='True' for c in pod['status'].get('conditions',[])))
  except RuntimeError:row['podAbsent']=True
  slices=h.obj('endpointslice','-l','kubernetes.io/service-name=orders')['items']
  row['endpoints']=[{'pod':e.get('targetRef',{}).get('name'),'conditions':e['conditions']} for s in slices for e in s['endpoints']]
  try:
   raw=json.loads(h.command(['docker','exec',target['spec']['nodeName'],'crictl','inspect',cid],timeout=10))['status']
   row['container']={k:raw.get(k) for k in ('state','exitCode','finishedAt','reason')}
  except RuntimeError:row['containerNotFound']=True
  observations.append(row);h.save(out/'pod-endpoint-observations.json',observations);stop.wait(.3)

def watch_readiness():
 while not stop.is_set():
  code=0;started=time.monotonic()
  try:
   with urlopen('http://127.0.0.1:18082/actuator/health/readiness',timeout=.5) as response:code=response.status
  except HTTPError as e:code=e.code
  except Exception:pass
  readiness.append({'at':h.now(),'status':code,'durationMs':round((time.monotonic()-started)*1000,2)})
  stop.wait(.1)

try:
 choices=op.db('inventory_db',"SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT route_id,travel_date,seat_id FROM seats WHERE status='AVAILABLE' AND route_id='rt-to-mi-001' AND travel_date>=CURRENT_DATE+10 ORDER BY travel_date,seat_id LIMIT 200) t")
 claims=h.obj('configmap','-l','eurotransit.io/load-test=true')['items'];claimed={tuple(json.loads(c['data']['fixture'])) for c in claims if c.get('data',{}).get('fixture')}
 choices=[s for s in choices if (s['route_id'],s['travel_date'],s['seat_id']) not in claimed][:4];assert len(choices)==4
 offer=next(o for o in h.request(h.BASE+'/api/catalog/offers') if o['routeId']=='rt-to-mi-001' and o['offerId']=='of-001')
 fixtures=[{'routeId':s['route_id'],'offerId':offer['offerId'],'travelDate':s['travel_date'],'seatId':s['seat_id'],'unitPrice':offer['price'],'currency':offer['currency']} for s in choices]
 for f in fixtures:
  key=json.dumps([f['routeId'],f['travelDate'],f['seatId']]);op.cm('et-fixture-'+hashlib.sha256(key.encode()).hexdigest()[:24],{'fixture':key,'runId':run_id})
 h.save(out/'fixtures.json',{'version':1,'fixtures':fixtures});auth=h.token()
 for _ in range(3):h.request(h.BASE+'/api/orders/seat-availability?routeId='+fixtures[0]['routeId']+'&travelDate='+fixtures[0]['travelDate'],token=auth)
 h.save(out/'run.json',meta);op.snapshot(out,'before')
 orders=h.obj('pods','-l','app=orders')['items'];assert len(orders)==2
 for p in orders:
  f=(out/(p['metadata']['name']+'.log')).open('w');handles.append(f);logs[p['metadata']['name']]=out/(p['metadata']['name']+'.log')
  streams.append(subprocess.Popen(['kubectl','--context',h.CONTEXT,'-n','eurotransit','logs','-f',p['metadata']['name'],'--timestamps','--since=1s'],stdout=f,stderr=subprocess.DEVNULL))
 f=fixtures[0];query="BEGIN; SET LOCAL statement_timeout=24000; SELECT seat_id FROM seats WHERE route_id='"+f['routeId']+"' AND travel_date='"+f['travelDate']+"' AND seat_id='"+f['seatId']+"' FOR UPDATE; SELECT 'BARRIER_HELD'; SELECT pg_sleep(18); ROLLBACK;"
 b=(out/'barrier.log').open('w');handles.append(b)
 barrier=subprocess.Popen(['kubectl','--context',h.CONTEXT,'-n','eurotransit','exec','-i',pre['primary'],'-c','postgres','--','psql','-X','-q','-t','-A','-v','ON_ERROR_STOP=1','-U','postgres','-d','inventory_db'],stdin=subprocess.PIPE,stdout=b,stderr=subprocess.STDOUT,text=True)
 barrier.stdin.write(query);barrier.stdin.close()
 deadline=time.monotonic()+5
 while 'BARRIER_HELD' not in (out/'barrier.log').read_text():
  assert barrier.poll() is None and time.monotonic()<deadline,'Barrier not acquired';time.sleep(.1)
 event('fixture_lock_acquired',maximumSeconds=24,nominalHoldSeconds=18)
 env=os.environ.copy();env.update(PUBLIC_URL=h.BASE,TOKEN_URL=h.ISSUER+'/protocol/openid-connect/token',CLIENT_ID='eurotransit-load-test',CLIENT_SECRET=h.secret('eurotransit-load-test-credentials','client-secret'),RUN_ID=run_id,SCENARIO='baseline',MAX_ATTEMPTS='4',MAX_VUS='1',POLL_TIMEOUT_SECONDS='30',ALLOW_INSECURE_TLS='true',OUTPUT_DIR=str(out),FIXTURES_FILE=str(out/'fixtures.json'))
 log=(out/'runner.log').open('w');handles.append(log);process=subprocess.Popen([sys.executable,str(ROOT/'load-tests/run.py')],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 deadline=time.monotonic()+10;oid=None
 while time.monotonic()<deadline and target is None:
  rows=op.db('orders_db',"SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT response_body::json->>'orderId' AS id FROM idempotency_keys WHERE key='"+run_id+"-0') t")
  if rows:
   oid=rows[0]['id']
   for pod in orders:
    if 'Running checkout pipeline for order '+oid in logs[pod['metadata']['name']].read_text():target=pod;break
  time.sleep(.1)
 assert target is not None,'No attributed in-flight listener observed; no shutdown injected'
 pending=h.request(h.BASE+'/api/orders/'+oid,token=auth);assert pending['status'] not in ('CONFIRMED','FAILED','CANCELLED'),'Order already terminal'
 h.save(out/'inflight-at-deletion.json',pending)
 cid=target['status']['containerStatuses'][0]['containerID'].split('://',1)[1]
 node=json.loads(h.command(['docker','inspect',target['spec']['nodeName']]))[0];assert node['Config']['Labels']['io.x-k8s.kind.cluster']=='eurotransit'
 forward=subprocess.Popen(['kubectl','--context',h.CONTEXT,'-n','eurotransit','port-forward','--address','127.0.0.1','pod/'+target['metadata']['name'],'18082:8080'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 for _ in range(30):
  try:
   with urlopen('http://127.0.0.1:18082/actuator/health/readiness',timeout=.5) as response:assert response.status==200
   break
  except Exception:time.sleep(.1)
 else:raise RuntimeError('Target readiness control not ready')
 for task in (watch_target,watch_readiness):
  t=threading.Thread(target=task,daemon=True);t.start();threads.append(t)
 event('pod_delete_requested',pod=target['metadata']['name'],uid=target['metadata']['uid'],inflightStatus=pending['status'],graceSeconds=target['spec']['terminationGracePeriodSeconds'])
 delete={'apiVersion':'v1','kind':'DeleteOptions','preconditions':{'uid':target['metadata']['uid']}}
 h.k('delete','--raw','/api/v1/namespaces/eurotransit/pods/'+target['metadata']['name'],'-f','-',data=json.dumps(delete))
 deadline=time.monotonic()+150
 while time.monotonic()<deadline:
  pods=h.obj('pods','-l','app=orders')['items'];ready=[p for p in pods if not p['metadata'].get('deletionTimestamp') and all(c.get('ready') for c in p['status'].get('containerStatuses',[])) and p['status'].get('containerStatuses')]
  if process.poll() is not None and len(ready)==2 and not any(p['metadata']['uid']==target['metadata']['uid'] for p in pods):break
  time.sleep(1)
 else:raise TimeoutError('Shutdown recovery deadline')
 meta.update(finishedAt=h.now(),exitCode=process.returncode);h.save(out/'run.json',meta);event('harness_and_replica_recovery_finished',harnessExitCode=process.returncode)
finally:
 stop.set()
 for t in threads:t.join(timeout=6)
 h.save(out/'readiness.json',readiness)
 if process and process.poll() is None:
  os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10)
 if barrier and barrier.poll() is None:
  barrier.terminate()
  try:barrier.wait(timeout=5)
  except subprocess.TimeoutExpired:barrier.kill();barrier.wait()
 if forward:forward.terminate();forward.wait(timeout=5)
 for p in streams:
  if p.poll() is None:p.terminate()
  p.wait(timeout=5)
 for f in handles:f.close()
 op.k('delete','configmap','eurotransit-load-test-lock')
op.snapshot(out,'after');original=h.collect(out,provider);final=h.final_audit(out,meta,provider);server=h.server_attribution_audit(out,meta,provider)
ready503=next((s['at'] for s in readiness if s['status']==503),None)
removed=next((s['at'] for s in observations if any(e['pod']==target['metadata']['name'] and e['conditions'].get('ready') is False for e in s.get('endpoints',[]))),None)
exitstates=[s['container'] for s in observations if s.get('container',{}).get('state')=='CONTAINER_EXITED']
result={'runId':run_id,'context':h.CONTEXT,'targetPod':target['metadata']['name'],'inflightStatusAtDeletion':pending['status'],'firstReadiness503At':ready503,'endpointExcludedAt':removed,'containerExit':exitstates[0] if exitstates else None,'originalClientVerified':original,'finalAudit':final,'serverAudit':server}
h.save(out/'result.json',result);print(json.dumps(result,indent=2));print('ARTIFACTS',out)
