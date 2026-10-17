{{- define "eurotransit.r2dbcPoolEnv" -}}
{{- $pool := .Values.global.database.r2dbcPool | default dict -}}
{{- if (get $pool "enabled" | default false) -}}
- name: SPRING_R2DBC_POOL_MAX_ACQUIRE_TIME
  value: {{ required "r2dbcPool.maxAcquireTime is required" $pool.maxAcquireTime | quote }}
- name: SPRING_R2DBC_POOL_MAX_CREATE_CONNECTION_TIME
  value: {{ required "r2dbcPool.maxCreateConnectionTime is required" $pool.maxCreateConnectionTime | quote }}
- name: SPRING_R2DBC_POOL_MAX_VALIDATION_TIME
  value: {{ required "r2dbcPool.maxValidationTime is required" $pool.maxValidationTime | quote }}
- name: SPRING_R2DBC_POOL_VALIDATION_QUERY
  value: "SELECT 1"
- name: SPRING_R2DBC_POOL_MAX_IDLE_TIME
  value: {{ required "r2dbcPool.maxIdleTime is required" $pool.maxIdleTime | quote }}
{{- end -}}
{{- end -}}
