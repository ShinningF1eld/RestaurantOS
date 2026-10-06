"use client";

import { ApiError, checkResponse } from "./errors";
import { loginPath, safeReturnPath } from "@/features/auth/paths";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export type AuthUser = { id: string; email: string; status: string };
let pendingRefresh: Promise<void> | null = null;
let failedRefresh: Error | null = null;
const channelName = "restaurantos-session";
const lockName = "restaurantos-session-mutation";

function broadcast(status: "active" | "signed-out") {
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(channelName);
  channel.postMessage(status);
  channel.close();
}

export function subscribeSession(listener: (status: "active" | "signed-out") => void) {
  if (typeof BroadcastChannel === "undefined") return () => {};
  const channel = new BroadcastChannel(channelName);
  channel.onmessage = (event: MessageEvent<unknown>) => {
    if (event.data === "active" || event.data === "signed-out") listener(event.data);
  };
  return () => channel.close();
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Invalid API path");
  const headers = new Headers(init.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes((init.method ?? "GET").toUpperCase())) {
    headers.set("X-CSRF-Protection", "1");
    if (init.body) headers.set("Content-Type", "application/json");
  }
  return fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
    redirect: "error",
  });
}

async function serialized<T>(operation: () => Promise<T>): Promise<T> {
  if (!navigator.locks)
    throw new ApiError("Please sign in again to renew your session in this browser.", 401);
  return navigator.locks.request(lockName, operation);
}

export function renewSession(): Promise<void> {
  if (failedRefresh) return Promise.reject(failedRefresh);
  if (!pendingRefresh) {
    pendingRefresh = serialized(async () => {
      if (failedRefresh) throw failedRefresh;
      // A different request/tab might have renewed while we waited for the lock.
      const current = await request("/auth/me");
      if (current.ok) return;
      if (current.status !== 401) {
        await checkResponse(current);
        return;
      }
      try {
        const refreshed = await request("/auth/refresh", { method: "POST" });
        await checkResponse(refreshed);
      } catch (failure) {
        // A consumed token's response might have been lost. Never let another
        // request automatically replay that token after this attempt finishes.
        failedRefresh =
          failure instanceof Error
            ? failure
            : new Error("Session renewal failed. Please sign in again.");
        throw failedRefresh;
      }
      // Renewal preserves identity and updates the shared cookies. Broadcasting
      // a login event would reload tabs while their rejected writes are retrying.
    }).finally(() => {
      pendingRefresh = null;
    });
  }
  return pendingRefresh;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let response = await request(path, init);
  if (response.status === 401) {
    try {
      await renewSession();
      // Only an explicit auth rejection is retried. Network and 5xx failures are not.
      response = await request(path, init);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        window.location.replace(loginPath(window.location.pathname + window.location.search));
      }
      throw error;
    }
  }
  if (response.status === 401)
    window.location.replace(loginPath(window.location.pathname + window.location.search));
  return checkResponse(response);
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const operation = async () => {
    const response = await checkResponse(
      await request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
    );
    failedRefresh = null;
    broadcast("active");
    return response.json() as Promise<AuthUser>;
  };
  return navigator.locks ? serialized(operation) : operation();
}

export async function logout(): Promise<void> {
  const operation = async () => {
    await checkResponse(await request("/auth/logout", { method: "POST" }));
    broadcast("signed-out");
  };
  if (navigator.locks) await serialized(operation);
  else await operation();
}

export async function currentUser(): Promise<AuthUser> {
  return (await apiFetch("/auth/me")).json();
}

export function currentReturnPath(): string {
  return safeReturnPath(window.location.pathname + window.location.search);
}
