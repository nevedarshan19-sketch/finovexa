export interface ContactPayload {
  name: string;
  email: string;
  organisation?: string;
  phone?: string;
  category: "general" | "support" | "partnership" | "developer";
  subject: string;
  message: string;
  consent: boolean;
  website?: string;
}

export interface ContactResponse {
  reference: string;
  message: string;
  note: string;
}
