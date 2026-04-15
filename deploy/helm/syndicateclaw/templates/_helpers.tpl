{{- /*
Expand the name of the chart.
*/ -}}
{{- define "syndicateclaw.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- /*
Create a default fully qualified app name.
*/ -}}
{{- define "syndicateclaw.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- /*
Create chart name and version as used by the chart label.
*/ -}}
{{- define "syndicateclaw.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- /*
Common labels
*/ -}}
{{- define "syndicateclaw.labels" -}}
app.kubernetes.io/name: {{ include "syndicateclaw.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- /*
Service account name
*/ -}}
{{- define "syndicateclaw.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "syndicateclaw.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- .Values.serviceAccount.name | default "default" }}
{{- end }}
{{- end }}
