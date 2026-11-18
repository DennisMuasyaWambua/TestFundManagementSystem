import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Money, RateBadge } from "@/components/money/Money";
import { StatusPill, toneFor } from "@/components/ui/StatusPill";
import { Stepper } from "@/components/ui/Stepper";

describe("Money", () => {
  it("renders an amount with tabular figures so a column lines up", () => {
    const { container } = render(<Money amount="5490667.23" />);
    const span = container.querySelector("span");
    expect(span).toHaveTextContent("5,490,667.23");
    expect(span?.className).toContain("tnum");
  });

  it("shows the currency when given one", () => {
    render(<Money amount="1000000.00" currency="USD" />);
    expect(screen.getByText("USD 1,000,000.00")).toBeInTheDocument();
  });

  it("mutes a zero balance only when asked", () => {
    const { container: muted } = render(<Money amount="0.00" muteZero />);
    expect(muted.querySelector("span")?.className).toContain("text-muted");

    const { container: plain } = render(<Money amount="0.00" />);
    expect(plain.querySelector("span")?.className).not.toContain("text-muted");
  });
});

describe("RateBadge", () => {
  it("renders a decimal rate as a percentage", () => {
    render(<RateBadge rate="0.0425" />);
    expect(screen.getByText("4.25%")).toBeInTheDocument();
  });

  it("renders an em dash when there is no rate", () => {
    render(<RateBadge rate={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("StatusPill", () => {
  /*
   * No meaning is carried by colour alone (WCAG 1.4.1). Each pill must spell its
   * state out in text as well, so the same information reaches someone who cannot
   * tell the success green from the warning amber.
   */
  it("always includes the state as readable text", () => {
    render(<StatusPill state="PENDING_APPROVAL" />);
    expect(screen.getByText("Pending approval")).toBeInTheDocument();
  });

  it("hides its decorative glyph from assistive technology", () => {
    const { container } = render(<StatusPill state="SETTLED" />);
    const glyph = container.querySelector('[aria-hidden="true"]');
    expect(glyph).not.toBeNull();
    expect(screen.getByText("Settled")).toBeInTheDocument();
  });

  it("maps each lifecycle state to a distinct tone", () => {
    expect(toneFor("SETTLED")).toBe("success");
    expect(toneFor("REJECTED")).toBe("danger");
    expect(toneFor("PENDING_APPROVAL")).toBe("progress");
    expect(toneFor("CANCELLED")).toBe("neutral");
    expect(toneFor("HELD")).toBe("warning");
    // An unknown state falls back to neutral rather than throwing.
    expect(toneFor("SOMETHING_NEW")).toBe("neutral");
  });
});

describe("Stepper", () => {
  it("announces each step's state in text, not only by colour", () => {
    render(
      <Stepper
        steps={[
          { label: "Prepared", state: "done" },
          { label: "Approved", state: "current" },
          { label: "Sent", state: "todo" },
        ]}
      />,
    );
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("current step")).toBeInTheDocument();
    expect(screen.getByText("not started")).toBeInTheDocument();
  });

  it("is an ordered list, so the sequence is conveyed structurally", () => {
    const { container } = render(
      <Stepper steps={[{ label: "Only", state: "current" }]} />,
    );
    expect(container.querySelector("ol")).not.toBeNull();
  });
});
