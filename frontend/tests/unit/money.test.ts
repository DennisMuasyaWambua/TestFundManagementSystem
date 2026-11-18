import { describe, expect, it } from "vitest";

import {
  formatMoney,
  formatRate,
  formatRatePct,
  isNegative,
  isZero,
} from "@/lib/money";

/**
 * The money formatter is the frontend's whole relationship with money: it formats
 * and never calculates. These tests pin the two things that would hurt a client --
 * losing a cent, and showing a credit as a debit -- and the precision cases where a
 * float would have drifted.
 */
describe("formatMoney", () => {
  it("groups thousands and always shows two decimals", () => {
    expect(formatMoney("5490667.23")).toBe("5,490,667.23");
    expect(formatMoney("1000000")).toBe("1,000,000.00");
    expect(formatMoney("0.5")).toBe("0.50");
    expect(formatMoney("999.999")).toBe("999.99");
  });

  it("keeps every digit of a 24-digit balance", () => {
    // A Number() round trip would round this; string formatting does not.
    expect(formatMoney("123456789012345678901.99")).toBe(
      "123,456,789,012,345,678,901.99",
    );
  });

  it("shows a negative in brackets", () => {
    expect(formatMoney("-10453.08")).toBe("(10,453.08)");
    expect(formatMoney("-10453.08", { brackets: false })).toBe("-10,453.08");
  });

  it("prefixes the currency when asked", () => {
    expect(formatMoney("1022268.84", { currency: "USD" })).toBe("USD 1,022,268.84");
    expect(formatMoney("-27168.72", { currency: "USD" })).toBe("(USD 27,168.72)");
  });

  it("renders nothing missing as an em dash, and passes through anything unparseable", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
    expect(formatMoney("")).toBe("—");
    expect(formatMoney("not a number")).toBe("not a number");
  });

  it("reproduces the golden-number figures exactly", () => {
    // Section 12: these are the figures a client's statement has to show.
    expect(formatMoney("5619061.17")).toBe("5,619,061.17");
    expect(formatMoney("7614827.62")).toBe("7,614,827.62");
    expect(formatMoney("516745.92")).toBe("516,745.92");
    expect(formatMoney("26198.63")).toBe("26,198.63");
    expect(formatMoney("1022268.84")).toBe("1,022,268.84");
    expect(formatMoney("19648.98")).toBe("19,648.98");
    expect(formatMoney("10137397.26")).toBe("10,137,397.26");
  });
});

describe("isNegative and isZero", () => {
  it("treats every spelling of zero as zero, not as negative", () => {
    for (const zero of ["0", "0.00", "-0.00", "0.000"]) {
      expect(isZero(zero)).toBe(true);
      expect(isNegative(zero)).toBe(false);
    }
  });

  it("recognises a real negative", () => {
    expect(isNegative("-0.01")).toBe(true);
    expect(isNegative("-5000000.00")).toBe(true);
    expect(isZero("-0.01")).toBe(false);
  });
});

describe("formatRatePct", () => {
  it("shifts the decimal point by string surgery, not multiplication", () => {
    // 0.0425 * 100 is 4.250000000000001 in IEEE 754 arithmetic.
    expect(formatRatePct("0.0425")).toBe("4.25%");
    expect(formatRatePct("0.035")).toBe("3.50%");
    expect(formatRatePct("0.10")).toBe("10.00%");
    expect(formatRatePct("0.05")).toBe("5.00%");
    expect(formatRatePct("0.00")).toBe("0.00%");
  });

  it("handles eight-decimal rates and whole percentages", () => {
    expect(formatRatePct("0.04250000")).toBe("4.25%");
    expect(formatRatePct("1.00000000")).toBe("100.00%");
    expect(formatRatePct("0.15", 0)).toBe("15%");
  });

  it("returns an em dash when there is no rate", () => {
    expect(formatRatePct(null)).toBe("—");
    expect(formatRatePct(undefined)).toBe("—");
  });
});

describe("formatRate", () => {
  it("trims trailing zeros but keeps the significant ones", () => {
    expect(formatRate("0.00800000")).toBe("0.008");
    expect(formatRate("0.00780000")).toBe("0.0078");
    expect(formatRate("0.00810000")).toBe("0.0081");
    expect(formatRate("1.00000000")).toBe("1");
  });
});
