import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataSources } from "./DataSources";

describe("DataSources", () => {
  it("names each source once, in a fixed order, with every table in the tooltip", () => {
    render(<DataSources sources={[
      { table_name: "circuit_markers", source: "earlier session at this circuit" },
      { table_name: "laps", source: "OpenF1 + TracingInsights" },
      { table_name: "results", source: "OpenF1 + Jolpica" },
    ]} />);
    const note = screen.getByText("Data: OpenF1 · Jolpica · TracingInsights");
    expect(note.getAttribute("title")).toContain("laps: OpenF1 + TracingInsights");
    expect(note.getAttribute("title")).toContain("circuit_markers: earlier session at this circuit");
  });

  it("says FastF1 for a session from before sources were recorded", () => {
    render(<DataSources sources={[{ table_name: "all", source: "FastF1" }]} />);
    expect(screen.getByText("Data: FastF1").getAttribute("title")).toBe("every table: FastF1");
  });

  it("shows nothing without sources", () => {
    const { container } = render(<DataSources sources={undefined} />);
    expect(container.textContent).toBe("");
  });
});
