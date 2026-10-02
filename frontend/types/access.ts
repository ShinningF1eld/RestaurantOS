export type Role = "OWNER" | "MANAGER" | "EMPLOYEE";

export type AccessContext = {
  organization_id: string;
  organization_number: number;
  role: Role;
  capabilities: string[];
  restaurant_ids: number[];
};

export type Membership = {
  id: string;
  user_id: string;
  organization_id: string;
  role: Role;
  status: "active" | "revoked";
};
