import type { Paged } from "./types";

const API_BASE_KEY = "corp.apiBase";
const API_KEY_KEY = "corp.apiKey";

export function getApiBase(): string {
  return (localStorage.getItem(API_BASE_KEY) || "http://localhost:8000").replace(/\/+$/, "");
}

export function setApiBase(value: string): void {
  localStorage.setItem(API_BASE_KEY, value);
}

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_KEY) || "";
}

export function setApiKey(value: string): void {
  localStorage.setItem(API_KEY_KEY, value);
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  const apiKey = getApiKey();
  if (apiKey) headers.set("X-Api-Key", apiKey);

  const res = await fetch(`${getApiBase()}${path}`, { ...init, headers });

  if (!res.ok) {
    let code = "error";
    let message = res.statusText;
    try {
      const body = await res.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(res.status, code, message);
  }
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function requestWithCount<T>(path: string, init?: RequestInit): Promise<Paged<T>> {
  const res = await send(path, init);
  const items = (await res.json()) as T[];
  const totalCount = Number(res.headers.get("X-Total-Count") ?? items.length);
  return { items, totalCount };
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  getWithCount: <T>(path: string) => requestWithCount<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
};
