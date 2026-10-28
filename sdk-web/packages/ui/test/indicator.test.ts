import type { IndicatorState } from "@certivo/sdk-types";
import { describe, expect, it } from "vitest";
import { createTrustIndicator, PLACEHOLDER_COPY } from "../src/index";

// A tiny stand-in for the browser's document: just the few things the indicator uses. (No DOM library on
// purpose: fewer dependencies to keep safe. The real browser behaviour is checked in P0-50's component gallery.)
class FakeElement {
  attrs = new Map<string, string>();
  children: FakeElement[] = [];
  textContent = "";
  className = "";
  removed = false;
  setAttribute(name: string, value: string) {
    this.attrs.set(name, value);
  }
  getAttribute(name: string) {
    return this.attrs.get(name) ?? null;
  }
  append(...nodes: FakeElement[]) {
    this.children.push(...nodes);
  }
  remove() {
    this.removed = true;
  }
}
const fakeDocument = { createElement: () => new FakeElement() } as unknown as Document;
const states: IndicatorState[] = ["stable", "borderline", "flagged", "paused"];

describe("the trust indicator", () => {
  it("starts in the paused state (never 'stable' before anything has been checked)", () => {
    const indicator = createTrustIndicator(fakeDocument);
    expect(indicator.state).toBe("paused");
    expect(indicator.element.getAttribute("data-state")).toBe("paused");
  });

  it("is announced politely to screen readers", () => {
    const { element } = createTrustIndicator(fakeDocument);
    expect(element.getAttribute("role")).toBe("status");
    expect(element.getAttribute("aria-live")).toBe("polite");
  });

  it("shows each state as words AND a symbol, never as colour alone", () => {
    const indicator = createTrustIndicator(fakeDocument);
    const [symbol, label] = (indicator.element as unknown as FakeElement).children;
    for (const state of states) {
      indicator.setState(state);
      expect(indicator.element.getAttribute("data-state")).toBe(state);
      expect(symbol?.textContent).toBe(PLACEHOLDER_COPY[state].symbol);
      expect(label?.textContent).toBe(PLACEHOLDER_COPY[state].label);
      expect(label?.textContent?.length).toBeGreaterThan(0);
    }
    expect(symbol?.getAttribute("aria-hidden")).toBe("true"); // the words carry the meaning for screen readers
  });

  it("gives every state its own symbol and its own words", () => {
    const symbols = new Set(states.map((s) => PLACEHOLDER_COPY[s].symbol));
    const labels = new Set(states.map((s) => PLACEHOLDER_COPY[s].label));
    expect(symbols.size).toBe(4);
    expect(labels.size).toBe(4);
  });

  it("can be removed", () => {
    const indicator = createTrustIndicator(fakeDocument);
    indicator.destroy();
    expect((indicator.element as unknown as FakeElement).removed).toBe(true);
  });
});
