import axios from "axios";

export interface DashboardMetrics {
  connectors_total: number;
  connectors_connected: number;
  connectors_errors: number;
  pending_approvals: number;
  workflow_runs_active: number;
  memory_namespaces: number;
}

export interface ConnectorStatus {
  platform: string;
  connected: boolean;
  webhook_url?: string | null;
  last_event_at?: string | null;
  events_received: number;
  errors: number;
  detail?: string | null;
}

export interface ApprovalQueueItem {
  id: string;
  actor: string;
  action: string;
  reason?: string | null;
  created_at: string;
  status: string;
}

export interface WorkflowRunSummary {
  run_id: string;
  status: string;
  workflow_name: string;
  initiated_by: string;
  created_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Provider {
  id: string;
  name: string;
  adapter_protocol: string;
  enabled?: boolean;
  status?: string;
  allowed_models?: string[];
}

export interface ProviderListResponse {
  system_config_version: string;
  inference_enabled: boolean;
  providers: Provider[];
}

export interface PolicyRule {
  id: string;
  name: string;
  description?: string | null;
  resource_type: string;
  resource_pattern: string;
  effect: "allow" | "deny" | string;
  conditions: Array<Record<string, unknown>>;
  priority: number;
  enabled: boolean;
  owner?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiKeySummary {
  key_id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at?: string | null;
  revoked: boolean;
}

export interface CreateApiKeyRequest {
  name: string;
  expires_at?: string | null;
}

export interface CreateApiKeyResponse {
  key_id: string;
  key: string;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  actor: string;
  domain: string;
  effect: string;
  action: string;
  at: string;
  detail: Record<string, unknown>;
}

export interface MemoryNamespaceSummary {
  namespace: string;
  prefix: string;
  records: number;
  last_updated_at?: string | null;
}

const client = axios.create({
  baseURL: "/",
});

client.interceptors.request.use((config) => {
  const key = localStorage.getItem("sc_api_key");
  if (key) {
    config.headers = config.headers ?? {};
    config.headers["X-API-Key"] = key;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && window.location.pathname !== "/console/login") {
      window.location.href = "/console/login";
    }
    return Promise.reject(error);
  }
);

export const adminApi = {
  dashboard: async (): Promise<DashboardMetrics> => {
    const { data } = await client.get<DashboardMetrics>("/api/v1/admin/dashboard");
    return data;
  },
  connectors: async (): Promise<ConnectorStatus[]> => {
    const { data } = await client.get<ConnectorStatus[]>("/api/v1/admin/connectors");
    return data;
  },
  approvalQueue: async (): Promise<ApprovalQueueItem[]> => {
    const { data } = await client.get<ApprovalQueueItem[]>("/api/v1/admin/approvals");
    return data;
  },
  decideApproval: async (id: string, accepted: boolean): Promise<Record<string, unknown>> => {
    const { data } = await client.post<Record<string, unknown>>(
      `/api/v1/admin/approvals/${id}/decide`,
      { accepted }
    );
    return data;
  },
  runs: async (params?: { limit?: number; status?: string }): Promise<WorkflowRunSummary[]> => {
    const { data } = await client.get<WorkflowRunSummary[]>("/api/v1/admin/workflows/runs", {
      params,
    });
    return data;
  },
  runById: async (runId: string): Promise<WorkflowRunSummary> => {
    const { data } = await client.get<WorkflowRunSummary>(`/api/v1/admin/workflows/runs/${runId}`);
    return data;
  },
  memoryNamespaces: async (prefix?: string): Promise<MemoryNamespaceSummary[]> => {
    const { data } = await client.get<MemoryNamespaceSummary[]>("/api/v1/admin/memory/namespaces", {
      params: prefix ? { prefix } : undefined,
    });
    return data;
  },
  purgeNamespace: async (namespace: string): Promise<Record<string, unknown>> => {
    const { data } = await client.delete<Record<string, unknown>>(
      `/api/v1/admin/memory/namespaces/${encodeURIComponent(namespace)}`
    );
    return data;
  },
  auditEvents: async (params?: {
    limit?: number;
    actor?: string;
    domain?: string;
    effect?: string;
    since?: string;
  }): Promise<AuditEvent[]> => {
    const { data } = await client.get<AuditEvent[]>("/api/v1/admin/audit", { params });
    return data;
  },
  providers: async (): Promise<Provider[]> => {
    const { data } = await client.get<Provider[]>("/api/v1/admin/providers");
    return data;
  },
  listApiKeys: async (): Promise<ApiKeySummary[]> => {
    const { data } = await client.get<ApiKeySummary[]>("/api/v1/admin/api-keys");
    return data;
  },
  createApiKey: async (body: CreateApiKeyRequest): Promise<CreateApiKeyResponse> => {
    const { data } = await client.post<CreateApiKeyResponse>("/api/v1/admin/api-keys", body);
    return data;
  },
  revokeApiKey: async (keyId: string): Promise<Record<string, unknown>> => {
    const { data } = await client.delete<Record<string, unknown>>(`/api/v1/admin/api-keys/${keyId}`);
    return data;
  },
};

export const providersApi = {
  list: async (): Promise<ProviderListResponse> => {
    const { data } = await client.get<ProviderListResponse>("/api/v1/providers/");
    return data;
  },
  syncModelsDev: async (): Promise<Record<string, unknown>> => {
    const { data } = await client.post<Record<string, unknown>>(
      "/api/v1/providers/catalog/sync-models-dev",
      {}
    );
    return data;
  },
};

export const policiesApi = {
  list: async (): Promise<PolicyRule[]> => {
    const { data } = await client.get<PolicyRule[]>("/api/v1/policies/");
    return data;
  },
  create: async (body: {
    name: string;
    description?: string;
    resource_type: string;
    resource_pattern: string;
    effect: string;
    priority: number;
    conditions?: Array<Record<string, unknown>>;
  }): Promise<PolicyRule> => {
    const { data } = await client.post<PolicyRule>("/api/v1/policies/", {
      ...body,
      conditions: body.conditions ?? [],
    });
    return data;
  },
  update: async (
    ruleId: string,
    body: Partial<{
      description: string;
      resource_pattern: string;
      effect: string;
      conditions: Array<Record<string, unknown>>;
      priority: number;
      enabled: boolean;
    }>
  ): Promise<PolicyRule> => {
    const { data } = await client.put<PolicyRule>(`/api/v1/policies/${ruleId}`, body);
    return data;
  },
  delete: async (ruleId: string): Promise<void> => {
    await client.delete(`/api/v1/policies/${ruleId}`);
  },
};

export const inferenceApi = {
  chat: async (messages: Array<{ role: string; content: string }>): Promise<string> => {
    const { data } = await client.post<{ content: string }>("/api/v1/inference/chat", { messages });
    return data.content;
  },
};
