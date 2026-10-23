{{- define "eurotransit.catalogDatabaseGate" -}}
- name: catalog-database-ready
  image: {{ .Values.catalog.database.wait.image | quote }}
  imagePullPolicy: IfNotPresent
  command: ["/bin/sh", "-ec"]
  args:
    - |
      deadline=$(( $(date +%s) + CATALOG_DATABASE_WAIT_SECONDS ))
      until psql -X --no-password --set=ON_ERROR_STOP=1 --set=catalog_database="$PGDATABASE" <<'SQL' >/dev/null 2>&1
      -- A non-owner causes division by zero and ON_ERROR_STOP aborts before REVOKE.
      -- Avoid dollar-quoted SQL: Kubernetes expands doubled dollar signs in args.
      SELECT 1 / (pg_get_userbyid(datdba) = current_user)::integer
        FROM pg_database WHERE datname = current_database();
      REVOKE CONNECT ON DATABASE :"catalog_database" FROM PUBLIC;
      SQL
      do
        if [ "$(date +%s)" -ge "$deadline" ]; then
          echo 'Catalog database is not ready within the startup budget.' >&2
          exit 1
        fi
        echo 'Waiting for the dedicated Catalog database and credentials.'
        sleep 2
      done
      echo 'Catalog database is ready; starting application migrations.'
  env:
    - name: PGHOST
      value: {{ .Values.global.database.host | quote }}
    - name: PGPORT
      value: {{ .Values.global.database.port | quote }}
    - name: PGDATABASE
      value: {{ .Values.catalog.database.name | quote }}
    - name: PGUSER
      valueFrom:
        secretKeyRef:
          name: {{ .Values.catalog.database.secretName | quote }}
          key: username
    - name: PGPASSWORD
      valueFrom:
        secretKeyRef:
          name: {{ .Values.catalog.database.secretName | quote }}
          key: password
    - name: PGCONNECT_TIMEOUT
      value: "5"
    - name: PGOPTIONS
      value: "-c statement_timeout=5000 -c lock_timeout=3000"
    - name: CATALOG_DATABASE_WAIT_SECONDS
      value: {{ .Values.catalog.database.wait.timeoutSeconds | quote }}
  resources:
    requests: {cpu: 10m, memory: 16Mi}
    limits: {cpu: 100m, memory: 64Mi}
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534
    runAsGroup: 65534
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: [ALL]
    seccompProfile:
      type: RuntimeDefault
{{- end -}}
