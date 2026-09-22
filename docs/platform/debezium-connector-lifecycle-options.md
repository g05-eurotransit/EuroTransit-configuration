# Lifecycle dei connector Debezium

Questo documento descrive il problema di bootstrap osservato nella pipeline
asincrona di acquisto di EuroTransit e confronta due alternative per gestire il
lifecycle dei connector Debezium in Kind e negli ambienti riconciliati da Argo
CD.

## Decisione implementata

È stata selezionata la soluzione B. EuroTransit usa un worker `KafkaConnect`
separato e un `KafkaConnector` dichiarativo con restart automatico per ogni
servizio con un outbox — Orders, Inventory e Payments (tre in tutto). L'immagine
compatibile con Strimzi viene costruita da `connect/Dockerfile` nel repository
applicativo: Kind la costruisce e carica localmente, mentre AKS usa l'artefatto
pubblicato in ACR e pinato per digest.

Il connector Payments segue lo stesso lifecycle di questo documento, ma il resto
dell'analisi — flusso, problema di bootstrap e verifica — riguarda `order-placed`
e quindi i soli connector Orders e Inventory: gli eventi di Payments oggi non
hanno consumatori e non guidano la saga di checkout.

## Flusso dell'acquisto

La creazione di un ordine e la sua elaborazione successiva avvengono in due
momenti distinti:

```text
Orders salva ordine ACCEPTED e order-placed nell'outbox
                            |
                            v
                  Debezium Orders relay
                            |
                            v
                     topic order-placed
                            |
                            v
                         Inventory
                            |
                            v
                Debezium Inventory relay
                            |
                            v
                         Payments
                            |
                            v
                 Orders CONFIRMED o FAILED
```

La risposta `ACCEPTED` indica quindi che Orders ha salvato la richiesta, non che
l'intera saga sia terminata. Debezium deve leggere gli eventi dalle tabelle
`public.outbox_events` di Orders e Inventory e pubblicarli su Kafka affinché il
flusso prosegua.

## Problema osservato

Durante un bootstrap da database vuoto, il setup ha eseguito queste operazioni:

1. ha creato PostgreSQL, Kafka e i worker Kafka Connect;
2. ha registrato i connector Debezium;
3. solo successivamente ha installato Orders e Inventory;
4. Flyway ha infine creato le rispettive tabelle `outbox_events`.

I connector usano:

```text
publication.autocreate.mode=filtered
table.include.list=public.outbox_events
```

Quando Debezium ha provato a creare la publication PostgreSQL, la tabella
indicata dal filtro non esisteva ancora. Entrambi i task sono quindi passati in
stato `FAILED` con l'errore:

```text
No table filters found for filtered publication
```

Il server Kafka Connect e i suoi endpoint HTTP sono rimasti attivi. Per questo
i Deployment e i pod risultavano `Ready`, mentre i task che dovevano trasferire
gli eventi erano fermi.

La verifica sul cluster ha mostrato:

- connector Orders e Inventory in stato `RUNNING`, ma task `0` in stato
  `FAILED`;
- un ordine fermo in `ACCEPTED`;
- il relativo evento `order-placed` presente nell'outbox Orders;
- nessun evento nell'outbox Inventory;
- nessun topic prodotto dai due connector.

La presenza dell'evento nell'outbox indica che la scrittura transazionale ha
funzionato. Il blocco si trova tra il database Orders e Kafka.

## Perché non avviene un retry automatico

Kafka Connect distingue lo stato del connector da quello dei task. Un connector
può rimanere `RUNNING` anche quando uno dei suoi task è `FAILED`. Kafka Connect
non riavvia automaticamente i task falliti; il riavvio deve essere richiesto
tramite REST API oppure da un controller esterno.

Debezium dispone di retry per errori classificati come temporanei. L'assenza di
una tabella che deve corrispondere a un filtro durante la creazione della
publication è invece un errore di startup: dopo aver corretto la precondizione,
il connector deve essere riavviato.

Le impostazioni generiche di error handling dei record non modificano questo
comportamento, perché intervengono durante conversione, trasformazione o
elaborazione degli eventi, non durante l'avvio del task.

## Requisiti comuni alle soluzioni

Indipendentemente dal meccanismo scelto, il risultato deve garantire che:

- le migrazioni Flyway siano terminate prima del primo avvio dei connector;
- il deployment sia considerato riuscito solo con connector e task `RUNNING`;
- le password dei database non siano stampate nei log;
- gli eventi già presenti nell'outbox vengano elaborati dopo un riavvio;
- un bootstrap da database vuoto sia verificato end-to-end;
- lo stato dei task, e non soltanto quello dei pod, sia osservabile.

## Soluzione A: Job Helm dopo il deploy

Questa soluzione conserva gli attuali Deployment basati su
`quay.io/debezium/connect` e continua a configurare Kafka Connect tramite REST
API.

Il Job viene dichiarato nel chart applicativo con gli hook Helm
`post-install,post-upgrade`. Helm lo esegue dopo aver caricato le risorse del
release; usando `--wait`, attende prima la readiness delle applicazioni. Argo CD
traduce gli stessi hook Helm in un hook `PostSync`.

Il Job esegue una riconciliazione one-shot:

1. attende la readiness di Orders o Inventory;
2. attende l'endpoint HTTP del relativo worker Kafka Connect;
3. invia con `PUT` la configurazione desiderata;
4. riavvia una volta un eventuale task già `FAILED`;
5. interroga lo status finché connector e task risultano `RUNNING`;
6. termina con errore se il task fallisce nuovamente o scade il timeout.

Il Job termina al completamento dell'installazione o dell'upgrade. Non rimane un
controller attivo e non interviene su un task che fallisce successivamente
durante il normale runtime.

### Implicazioni

- Non cambia l'immagine o il processo dei worker Kafka Connect.
- Conserva group ID, internal topic e offset correnti senza migrazione.
- Un errore del Job fa fallire direttamente l'operazione Helm o la sync Argo.
- La configurazione viene riconciliata soltanto durante install e upgrade.
- La REST API conserva la configurazione nel config topic del worker.
- La delete o il rollback dei connector richiedono una gestione esplicita del
  relativo lifecycle REST.
- Il Job deve evitare di stampare la risposta completa del `PUT`, perché può
  contenere la configurazione del database.

## Soluzione B: risorse Strimzi dichiarative

Questa soluzione sostituisce i Deployment Kafka Connect e i Job REST con
risorse `KafkaConnect` e `KafkaConnector` gestite dall'operatore Strimzi già
presente nel cluster.

Il deployment viene suddiviso in tre fasi esplicite:

```text
wave 20: PostgreSQL e Kafka
wave 30: applicazioni e migrazioni Flyway
wave 40: KafkaConnect e KafkaConnector
```

In locale, `kind-up` riproduce lo stesso ordine applicando i connector dopo un
`helm upgrade --install --wait`. In Argo CD, una Application dedicata ai
connector viene sincronizzata dopo il marketplace.

Ogni `KafkaConnector` contiene la configurazione Debezium e abilita il
meccanismo Strimzi:

```yaml
spec:
  autoRestart:
    enabled: true
    maxRestarts: 10
```

L'operatore osserva continuamente connector e task, applica restart con backoff
e pubblica lo stato nel campo `.status` della risorsa. Per fare in modo che una
sync Argo fallisca in base a tale stato è necessaria una health customization
per i `KafkaConnector`.

### Implicazioni

- Serve un'immagine Kafka Connect compatibile con Strimzi contenente il plugin
  Debezium PostgreSQL e Outbox EventRouter.
- L'immagine deve essere costruita, pubblicata, versionata e resa disponibile
  sia a Kind sia ad AKS.
- `EnvVarConfigProvider` mantiene nei manifest e nei config topic un
  riferimento alla variabile; il valore viene montato dal Secret soltanto nel
  container del relativo worker.
- Strimzi riconcilia continuamente configurazione, stato e restart.
- La cancellazione del `KafkaConnector` rimuove dichiarativamente il connector.
- Mantenendo due `KafkaConnect`, gli stessi group ID e gli stessi internal topic
  è possibile conservare l'isolamento e gli offset esistenti; una successiva
  unificazione dei worker richiederebbe una migrazione separata.
- Il runtime diventa dipendente dalle CRD e dal controller Strimzi.

## Confronto

| Aspetto | Job Helm post-deploy | `KafkaConnect` / `KafkaConnector` Strimzi |
| --- | --- | --- |
| Modello | Procedura one-shot | Riconciliazione continua |
| Ordinamento iniziale | Hook dopo la readiness applicativa | Application/wave dopo il marketplace |
| Registrazione | REST API Kafka Connect | Risorsa Kubernetes |
| Race con Flyway | Eliminata dal Job | Eliminata dall'ordine delle wave |
| Task già fallito | Restart esplicito nel Job | `autoRestart` con backoff |
| Guasto runtime successivo | Non gestito dal Job terminato | Gestito dall'operatore |
| Configuration drift | Corretto al successivo deploy | Corretto a ogni riconciliazione |
| Stato | Endpoint REST | `.status` della CR |
| Gating del deploy | Fallimento diretto del Job | Health customization Argo |
| Secret | Valore inviato via REST | Riferimento tramite `EnvVarConfigProvider` |
| Immagine corrente | Invariata | Nuova immagine plugin compatibile con Strimzi |
| Offset esistenti | Invariati | Da preservare tramite group ID e internal topic |
| Cleanup | Gestione REST esplicita | Cancellazione dichiarativa del CR |
| Portata della modifica | Chart, Job, script e test | Immagine, CR, RBAC, overlay, GitOps e migrazione |
| Dipendenza operativa | Kafka Connect, Helm e REST | Kafka Connect e operatore Strimzi |

## Verifica causale eseguita sul cluster

La diagnosi è stata confermata riavviando i soli task falliti dopo che Flyway
aveva creato le tabelle:

```bash
kubectl -n eurotransit exec deployment/orders-outbox-connect -- \
  curl -fsS -X POST \
  'http://localhost:8083/connectors/orders-outbox-connector/restart?includeTasks=true&onlyFailed=true'

kubectl -n eurotransit exec deployment/inventory-outbox-connect -- \
  curl -fsS -X POST \
  'http://localhost:8083/connectors/inventory-outbox-connector/restart?includeTasks=true&onlyFailed=true'
```

Il test ha fatto ripartire la pipeline senza inserire un nuovo evento. Questo
conferma che l'evento era correttamente persistito nell'outbox e che il blocco
era il task Debezium fallito durante il bootstrap.

I criteri usati per la verifica sono stati:

1. entrambi i task passano a `RUNNING`;
2. il connector Orders pubblica l'evento già presente nell'outbox;
3. Inventory genera `inventory-reserved` o `inventory-failed`;
4. l'ordine lascia `ACCEPTED` e raggiunge uno stato terminale;
5. non è necessario inserire manualmente un nuovo evento.

Il raggiungimento di `CONFIRMED` dipende anche dall'esito del provider di
pagamento. Uno stato terminale `FAILED` dimostra comunque che la pipeline
asincrona ha ripreso a elaborare l'ordine.

## Verifica della migrazione Strimzi

La migrazione sul cluster Kind esistente ha conservato topic interni, connector
name, slot e publication. Al termine:

- entrambi i `KafkaConnect` e i `KafkaConnector` risultavano `Ready=True`;
- entrambi i connector e i rispettivi task `0` risultavano `RUNNING`;
- il worker usava l'heap esplicito `-Xms128m -Xmx512m` senza restart;
- l'ordine precedentemente bloccato risultava `CONFIRMED`.

Il primo avvio ha inoltre mostrato perché l'heap va dichiarato: il calcolo
automatico vedeva la memoria dell'host Kind e richiedeva circa 12 GiB dentro un
container limitato a 768 MiB, causando `OOMKilled`. Gli overlay Kind e AKS
impostano quindi un heap coerente con il limite. Una configurazione connector
volutamente invalida è stata esposta da Strimzi come `NotReady` ed è tornata
`Ready` dopo il ripristino dichiarativo. Il restart automatico di un task
fallito resta uno scenario esplicito del test di accettazione.

È stato verificato anche il bootstrap da zero cancellando e ricreando il cluster
Kind. `kind-up` ha applicato marketplace e migrazioni prima dei CR dei connector;
entrambi i `KafkaConnect` e i `KafkaConnector` sono diventati `Ready=True` senza
interventi manuali. Le API Connect riportavano connector e task `0` in stato
`RUNNING`, i pod avevano zero restart e nei log non compariva l'errore
`No table filters found for filtered publication`.

## Test di accettazione della correzione

Per entrambe le soluzioni devono essere coperti almeno questi scenari:

1. bootstrap di un cluster con database vuoti;
2. verifica delle migrazioni prima dell'avvio dei task;
3. connector e task entrambi `RUNNING` prima di dichiarare il deployment pronto;
4. ordine che passa da `ACCEPTED` a uno stato terminale;
5. evento già presente nell'outbox durante un restart;
6. errore permanente di configurazione che rende visibile il fallimento del
   deployment;
7. assenza di password e payload di pagamento nei log;
8. conservazione degli offset durante upgrade e rollback.

Per la soluzione Strimzi vanno inoltre verificati il backoff automatico, lo
stato del `KafkaConnector`, la health customization Argo, il build/load
dell'immagine in Kind e il pull da ACR in AKS.

## Rollback

Il rollback non deve cancellare i topic Kafka Connect interni, gli slot di
replicazione o le publication PostgreSQL. Si rimuovono prima i
`KafkaConnector` e i `KafkaConnect`, quindi si ripristinano i precedenti
Deployment e Job mantenendo gli stessi connector name, group ID e topic
interni. In questo modo il worker legacy riprende dagli offset già registrati.

## Riferimenti

- [Debezium PostgreSQL connector 2.7](https://debezium.io/documentation/reference/2.7/connectors/postgresql.html)
- [Kafka Connect administration](https://kafka.apache.org/37/kafka-connect/administration/)
- [Kafka Connect REST API](https://kafka.apache.org/37/kafka-connect/user-guide/)
- [Helm chart hooks](https://docs.helm.sh/docs/topics/charts_hooks/)
- [Argo CD mapping degli hook Helm](https://argo-cd.readthedocs.io/en/latest/user-guide/helm/)
- [Strimzi 0.46.1 configuration](https://strimzi.io/docs/operators/0.46.1/configuring)
