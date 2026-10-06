import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api";
import { ExportDialog } from "@/components/ExportDialog";
import { ToastProvider } from "@/components/ui/toast";

const renderDialog = (onClose = vi.fn()) =>
  render(
    <ToastProvider>
      <ExportDialog open onClose={onClose} />
    </ToastProvider>,
  );

const options = [
  {
    report_id: "rep1",
    name: "Acme 2024",
    versions: [
      { run_id: "r2", version_number: 2 },
      { run_id: "r1", version_number: 1 },
    ],
  },
  {
    report_id: "rep2",
    name: "Globex",
    versions: [{ run_id: "r3", version_number: 1 }],
  },
];

beforeEach(() => vi.restoreAllMocks());

describe("ExportDialog", () => {
  it("lists reports, each with a version picker defaulting to latest", async () => {
    vi.spyOn(client, "getExportOptions").mockResolvedValue(options);
    renderDialog();

    expect(await screen.findByText("Acme 2024")).toBeInTheDocument();
    expect(screen.getByText("Globex")).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
    expect(screen.getByRole("combobox", { name: /version for acme/i })).toHaveValue("r2");
    expect(screen.getByRole("combobox", { name: /version for globex/i })).toHaveValue("r3");
  });

  it("disables Download until a report is selected, then downloads the chosen runs", async () => {
    vi.spyOn(client, "getExportOptions").mockResolvedValue(options);
    const dl = vi.spyOn(client, "downloadFile").mockImplementation(() => {});
    const onClose = vi.fn();
    renderDialog(onClose);
    await screen.findByText("Acme 2024");

    const download = screen.getByRole("button", { name: /download/i });
    expect(download).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: /globex/i }));
    expect(download).toBeEnabled();
    await userEvent.click(download);

    expect(dl).toHaveBeenCalledWith(expect.stringContaining("runs=r3"));
    expect(onClose).toHaveBeenCalled();
  });

  it("exports the chosen version for a multi-version report (default latest)", async () => {
    vi.spyOn(client, "getExportOptions").mockResolvedValue(options);
    const dl = vi.spyOn(client, "downloadFile").mockImplementation(() => {});
    renderDialog();
    await screen.findByText("Acme 2024");

    await userEvent.click(screen.getByRole("checkbox", { name: /acme/i }));
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: /version for acme/i }),
      "r1",
    );
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    expect(dl).toHaveBeenCalledWith(expect.stringContaining("runs=r1"));
  });
});
