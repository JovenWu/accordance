import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { NotFoundPage } from "@/pages/NotFoundPage";

const renderPage = (ui: React.ReactElement) =>
  render(<MemoryRouter>{ui}</MemoryRouter>);

describe("NotFoundPage", () => {
  it("states the code and a default explanation", () => {
    renderPage(<NotFoundPage />);
    expect(screen.getByText("404")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
  });

  it("always offers a way back", () => {
    renderPage(<NotFoundPage />);
    expect(
      screen.getByRole("link", { name: /back to analyses/i }),
    ).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("takes resource-specific copy", () => {
    renderPage(
      <NotFoundPage
        title="Report not found"
        message="That report doesn't exist. It may have been deleted."
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Report not found" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/may have been deleted/i)).toBeInTheDocument();
    expect(screen.getByText("404")).toBeInTheDocument();
  });
});
