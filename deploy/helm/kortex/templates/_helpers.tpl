{{/*
Common template helpers.
*/}}

{{- define "kortex.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "kortex.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "kortex.labels" -}}
app.kubernetes.io/name: {{ include "kortex.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "kortex.matchLabels" -}}
app.kubernetes.io/name: {{ include "kortex.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "kortex.image" -}}
{{- $registry := .Values.image.registry -}}
{{- $repo := .repo -}}
{{- $tag := .tag -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- end -}}

{{- define "kortex.envCommon" -}}
- name: KORTEX_ENV
  value: {{ .Values.env | quote }}
- name: KORTEX_DATABASE_URL
  value: {{ .Values.postgres.url | quote }}
- name: KORTEX_REDIS_URL
  value: {{ .Values.redis.url | quote }}
- name: KORTEX_S3_ENDPOINT_URL
  value: {{ .Values.s3.endpointUrl | quote }}
- name: KORTEX_S3_REGION
  value: {{ .Values.s3.region | quote }}
- name: KORTEX_S3_BUCKET
  value: {{ .Values.s3.bucket | quote }}
- name: KORTEX_S3_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.s3.accessKeyExistingSecret }}
      key: {{ .Values.s3.accessKeySecretKey }}
- name: KORTEX_S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.s3.secretKeyExistingSecret }}
      key: {{ .Values.s3.secretKeySecretKey }}
- name: KORTEX_JWT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ .Values.jwt.existingSecret }}
      key: {{ .Values.jwt.existingSecretKey }}
- name: KORTEX_OTEL_ENABLED
  value: "true"
- name: KORTEX_OTEL_ENDPOINT
  value: {{ .Values.observability.otelExporter | quote }}
{{- end -}}
