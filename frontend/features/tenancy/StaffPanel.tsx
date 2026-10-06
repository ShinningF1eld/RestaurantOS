"use client";

import { useState } from "react";
import { addMembership, changeRole, getMemberships, revokeMembership } from "@/lib/api/access";
import type { Membership, Role } from "@/types/access";

export default function StaffPanel({
  initialMembers,
  restaurantId,
}: {
  initialMembers: Membership[];
  restaurantId: number;
}) {
  const [members, setMembers] = useState(initialMembers);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("EMPLOYEE");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function mutate(operation: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await operation();
      setMembers(await getMemberships());
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not update staff access.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <form
        className="flex flex-wrap items-end gap-4 rounded-lg border border-slate-200 bg-white p-5"
        onSubmit={(event) => {
          event.preventDefault();
          void mutate(async () => {
            await addMembership(email, role, role === "OWNER" ? [] : [restaurantId]);
            setEmail("");
          });
        }}
      >
        <label className="grid gap-1 text-sm">
          Provisioned account email
          <input
            required
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="rounded-md border border-slate-300 p-2"
          />
        </label>
        <label className="grid gap-1 text-sm">
          Role
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
            className="rounded-md border border-slate-300 p-2"
          >
            <option value="EMPLOYEE">Employee</option>
            <option value="MANAGER">Manager</option>
            <option value="OWNER">Owner</option>
          </select>
        </label>
        <button
          disabled={busy}
          className="rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          Add staff
        </button>
        <p className="w-full text-sm text-slate-500">
          Managers and employees added here receive access to this restaurant. Owners have access to
          every restaurant in the organization.
        </p>
      </form>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b">
              <th className="p-4">User ID</th>
              <th className="p-4">Role</th>
              <th className="p-4">Status</th>
              <th className="p-4">Access</th>
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr key={member.id} className="border-b last:border-0">
                <td className="p-4">{member.user_id}</td>
                <td className="p-4">
                  <select
                    aria-label={`Role for ${member.user_id}`}
                    value={member.role}
                    disabled={busy || member.status !== "active"}
                    onChange={(event) => {
                      const selected = event.target.value as Role;
                      void mutate(() => changeRole(member.id, selected));
                    }}
                    className="rounded-md border border-slate-300 p-2"
                  >
                    <option value="OWNER">Owner</option>
                    <option value="MANAGER">Manager</option>
                    <option value="EMPLOYEE">Employee</option>
                  </select>
                </td>
                <td className="p-4">{member.status}</td>
                <td className="p-4">
                  {member.status === "active" && (
                    <button
                      disabled={busy}
                      onClick={() => void mutate(() => revokeMembership(member.id))}
                      aria-label={`Revoke access for ${member.user_id}`}
                      className="font-semibold text-red-700 disabled:opacity-50"
                    >
                      Revoke access
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
