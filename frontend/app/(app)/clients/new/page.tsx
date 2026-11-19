import type { Metadata } from "next";

import { NewClientForm } from "@/app/(app)/clients/new/NewClientForm";
import { PageHeader } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "New client" };

export default function NewClientPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Onboard a client"
        description="This is step one of three. A mandate still needs compliance to approve KYC and finance to add a custody account before any instruction can be raised for it."
      />

      <NewClientForm />
    </div>
  );
}
