import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScorePill } from "./chip";

describe("ScorePill", () => {
  it("gives each score a distinct color", () => {
    const classes = [1, 2, 3, 4, 5].map((score) => {
      const { container, unmount } = render(<ScorePill score={score} />);
      const cls = container.firstElementChild!.className;
      unmount();
      return cls;
    });
    expect(new Set(classes).size).toBe(5);
    for (const cls of classes) {
      expect(cls).toMatch(/bg-(success|lime|warning|orange|danger)-soft/);
    }
  });

  it("renders a neutral pill for missing scores", () => {
    render(<ScorePill score={null} />);
    expect(screen.getByText("No score")).toBeInTheDocument();
    expect(screen.getByText("!")).toBeInTheDocument();
  });
});
