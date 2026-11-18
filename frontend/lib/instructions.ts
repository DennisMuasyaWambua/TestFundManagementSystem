import type { InstructionStatus, InstructionType } from "@/lib/api/schema";

export const INSTRUCTION_TYPE_LABEL: Record<InstructionType, string> = {
  PLACE_WAKALA: "Place a Wakala deposit",
  BUY_SUKUK: "Buy Sukuk",
  DISBURSE_FINANCING: "Disburse private financing",
  PURCHASE_PROPERTY: "Purchase investment property",
  PAY_CLIENT_PROFIT: "Pay profit to the client",
  RETURN_CAPITAL: "Return capital to the client",
  PAY_MGMT_FEE: "Pay the management fee",
  PAY_CUSTODY_FEE: "Pay the custody fee",
  FX_CONVERSION: "Convert currency",
};

/** The instruction types that create a holding, and therefore need deal terms. */
export const INVESTMENT_TYPES: InstructionType[] = [
  "PLACE_WAKALA",
  "BUY_SUKUK",
  "DISBURSE_FINANCING",
  "PURCHASE_PROPERTY",
];

/** The types that pay the client, and therefore need the client's written request. */
export const CLIENT_REQUEST_TYPES: InstructionType[] = ["PAY_CLIENT_PROFIT", "RETURN_CAPITAL"];

export function isInvestment(type: InstructionType): boolean {
  return INVESTMENT_TYPES.includes(type);
}

export function needsClientRequest(type: InstructionType): boolean {
  return CLIENT_REQUEST_TYPES.includes(type);
}

/**
 * The five steps of the instruction lifecycle, resolved against a status.
 *
 * A rejected or cancelled instruction stops where it stopped: its remaining steps
 * are shown as never reached rather than as still to come, because they will not be.
 */
export function lifecycleSteps(
  status: InstructionStatus,
  approvals: number,
): { label: string; state: "done" | "current" | "todo" | "failed"; detail?: string }[] {
  const order: InstructionStatus[] = ["PENDING_APPROVAL", "APPROVED", "SENT", "SETTLED"];
  const ended = status === "REJECTED" || status === "CANCELLED";

  const labels = [
    { label: "Prepared", detail: "raised by operations" },
    {
      label: "Approved",
      detail: `${approvals} of 2 authorised signatures`,
    },
    { label: "Letter signed and sent", detail: "wet-signed scan on file" },
    { label: "Custodian confirmed", detail: "settlement booked to the ledger" },
  ];

  if (ended) {
    const reachedIndex = status === "REJECTED" ? 1 : Math.max(1, approvals > 0 ? 1 : 0);
    return [
      ...labels.slice(0, reachedIndex).map((step) => ({ ...step, state: "done" as const })),
      {
        label: status === "REJECTED" ? "Rejected" : "Cancelled",
        state: "failed" as const,
        detail: "this instruction will not be sent",
      },
    ];
  }

  const currentIndex = order.indexOf(status);
  return labels.map((step, index) => ({
    ...step,
    state:
      index < currentIndex
        ? ("done" as const)
        : index === currentIndex
          ? ("current" as const)
          : ("todo" as const),
  }));
}
