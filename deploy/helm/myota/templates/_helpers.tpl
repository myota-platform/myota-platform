{{- define "myota.name" -}}myota{{- end }}
{{- define "myota.fullname" -}}{{ include "myota.name" . }}-{{ .name }}{{- end }}

