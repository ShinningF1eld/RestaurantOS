import { apiFetch } from "./client";
import type { AccessContext, Membership, Role } from "@/types/access";

export const getAccess = async (): Promise<AccessContext> => (await apiFetch("/api/access")).json();
export const getMemberships = async (): Promise<Membership[]> =>
  (await apiFetch("/api/memberships")).json();
export const addMembership = async (
  email: string,
  role: Role,
  restaurantIds: number[],
): Promise<Membership> =>
  (
    await apiFetch("/api/memberships", {
      method: "POST",
      body: JSON.stringify({ email, role, restaurant_ids: restaurantIds }),
    })
  ).json();
export const changeRole = async (id: string, role: Role): Promise<Membership> =>
  (
    await apiFetch(`/api/memberships/${id}`, { method: "PUT", body: JSON.stringify({ role }) })
  ).json();
export const revokeMembership = async (id: string): Promise<void> => {
  await apiFetch(`/api/memberships/${id}`, { method: "DELETE" });
};
