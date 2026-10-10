{{- define "myota.name" -}}myota{{- end }}
{{- define "myota.fullname" -}}{{ include "myota.name" . }}-{{ .name }}{{- end }}
{{- define "myota.imageReference" -}}
{{- $repository := required "imageReference.repository is required" .repository -}}
{{- $digest := default "" .digest -}}
{{- if $digest -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else -}}
{{- printf "%s:%s" $repository (default "latest" .tag) -}}
{{- end -}}
{{- end }}
{{- define "myota.waitForSchema" -}}
- name: wait-for-schema
  image: {{ .root.Values.migrations.waitImage | quote }}
  imagePullPolicy: IfNotPresent
  env:
    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: {{ .root.Values.postgres.existingSecret }}
          key: {{ .databaseUrlKey }}
    - name: EXPECTED_SCHEMA_REVISION
      value: {{ .root.Release.Revision | quote }}
  command: ["/bin/sh", "-ec"]
  args:
    - |
      deadline=$(( $(date +%s) + {{ .root.Values.migrations.waitTimeoutSeconds }} ))
      until [ "$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -Atqc "SELECT ready FROM public.myota_deployment_schema_state WHERE id = 'deployment' AND release_revision = ${EXPECTED_SCHEMA_REVISION}" 2>/dev/null || true)" = "t" ]; do
        if [ "$(date +%s)" -ge "$deadline" ]; then
          echo "Timed out waiting for the MyOTA database migrations to finish"
          exit 1
        fi
        sleep 5
      done
{{- end }}
