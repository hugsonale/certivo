import type { IndicatorState } from "@certivo/sdk-types";

/**
 * PLACEHOLDER WORDING. The real copy is written and approved in step P0-38 (non-alarmist tone, Doc 13
 * section 6 and Doc 14 section 2). Nothing here may be shown to real users.
 */
export const PLACEHOLDER_COPY: Record<IndicatorState, { symbol: string; label: string }> = {
  stable: { symbol: "\u2713", label: "Verification: steady" },
  borderline: { symbol: "~", label: "Verification: checking" },
  flagged: { symbol: "!", label: "Verification: needs a look" },
  paused: { symbol: "\u2016", label: "Verification: paused" },
};

export interface TrustIndicator {
  readonly element: HTMLElement;
  readonly state: IndicatorState;
  setState(state: IndicatorState): void;
  destroy(): void;
}

/**
 * The in-call trust indicator, reference version. Every state has visible words AND a different symbol:
 * it never relies on colour alone (guide P0-50), and it is announced politely to screen readers.
 * Colours and layout come from the design tokens in P0-50; this only sets `data-state` for them to use.
 */
export function createTrustIndicator(doc: Document = document, initial: IndicatorState = "paused"): TrustIndicator {
  const element = doc.createElement("div");
  element.setAttribute("role", "status");
  element.setAttribute("aria-live", "polite");
  element.className = "certivo-trust-indicator";
  const symbol = doc.createElement("span");
  symbol.setAttribute("aria-hidden", "true");
  const label = doc.createElement("span");
  element.append(symbol, label);

  let current: IndicatorState = initial;
  const render = () => {
    const copy = PLACEHOLDER_COPY[current];
    element.setAttribute("data-state", current);
    symbol.textContent = copy.symbol;
    label.textContent = copy.label;
  };
  render();

  return {
    element,
    get state() {
      return current;
    },
    setState(state) {
      if (state === current) return;
      current = state;
      render();
    },
    destroy() {
      element.remove();
    },
  };
}
