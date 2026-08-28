import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import {
  DeniedState,
  EmptyState,
  ErrorState,
  MalformedState,
  UnavailableState,
} from "@/components/states/StateViews";
import { ChartFrame } from "@/components/charts/ChartFrame";
import { ProbabilityBar } from "@/components/ui/primitives";
import { GlobalFilters } from "@/components/filters/GlobalFilters";
import { useGlobalFilters } from "@/components/filters/useGlobalFilters";
import {
  AccessDeniedError,
  ApiUnavailableError,
  MalformedResponseError,
} from "@/lib/api/errors";

describe("state views", () => {
  it("52. says something different for empty, unavailable and denied", () => {
    // Collapsing these is how a console tells an analyst a district has no risk
    // when the source feeding it has been down for six days.
    const { unmount } = render(<EmptyState />);
    expect(screen.getByText(/returned nothing/i)).toBeInTheDocument();
    unmount();

    const second = render(<UnavailableState error={new ApiUnavailableError("/v1/forecasts")} />);
    expect(screen.getByText(/could not be reached/i)).toBeInTheDocument();
    expect(screen.getByText("/v1/forecasts")).toBeInTheDocument();
    second.unmount();

    render(<DeniedState error={new AccessDeniedError("evidence ev_1", "analyst")} />);
    // Exact-case match: the body copy also contains "not permitted", and a
    // loose regex here would pass even if the heading disappeared.
    expect(screen.getByText("Not permitted")).toBeInTheDocument();
    expect(screen.getByText("evidence ev_1")).toBeInTheDocument();
    expect(screen.getByText("analyst")).toBeInTheDocument();
  });

  it("53. lists contract violations instead of rendering the payload", () => {
    render(
      <MalformedState
        error={new MalformedResponseError("/v1/forecasts", ["calibrated_probability: probability above 1"])}
      />,
    );
    expect(screen.getByText(/failed contract validation/i)).toBeInTheDocument();
    expect(screen.getByText(/probability above 1/)).toBeInTheDocument();
  });

  it("54. routes each error class to its own view and never blanks the panel", () => {
    const { unmount } = render(<ErrorState error={new AccessDeniedError("x")} />);
    expect(screen.getByText("Not permitted")).toBeInTheDocument();
    unmount();

    render(<ErrorState error={new Error("something unexpected")} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText(/something unexpected/)).toBeInTheDocument();
  });
});

describe("charts", () => {
  it("55. exposes the underlying numbers as a real table", async () => {
    const user = userEvent.setup();
    render(
      <ChartFrame
        title="Reliability"
        description="Observed against predicted."
        columns={["Bin", "n"]}
        rows={[["0.0–0.1", 412], ["0.9–1.0", 9]]}
      >
        <svg aria-hidden />
      </ChartFrame>,
    );
    await user.click(screen.getByRole("button", { name: /show data table/i }));
    // The sparse top bin is the whole reason the table exists: nine samples is
    // not a calibration claim, and the chart cannot say so.
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("412")).toBeInTheDocument();
  });
});

describe("probability bar", () => {
  it("56. states the number as well as drawing it, and says when there is no interval", () => {
    const { unmount } = render(
      <ProbabilityBar value={0.62} interval={{ lower: 0.5, upper: 0.7, coverage: 0.9, method: "m" }} />,
    );
    expect(screen.getByText("62%")).toBeInTheDocument();
    expect(screen.getByLabelText(/62%, 50% – 70% interval/)).toBeInTheDocument();
    unmount();

    render(<ProbabilityBar value={0.62} interval={null} />);
    expect(screen.getByLabelText(/no interval/)).toBeInTheDocument();
  });
});

function FilterHarness() {
  const { filters, setFilters, query } = useGlobalFilters();
  const [params] = useSearchParams();
  return (
    <>
      <GlobalFilters
        filters={filters}
        states={["Bihar", "Kerala"]}
        onChange={setFilters}
        resultCount={3}
        totalCount={10}
      />
      <output data-testid="url">{params.toString()}</output>
      <output data-testid="query">{JSON.stringify(query)}</output>
    </>
  );
}

describe("global filters", () => {
  it("57. reads its initial state from the URL", () => {
    render(
      <MemoryRouter future={{ v7_relativeSplatPath: true }} initialEntries={["/?family=flood&status=alert&min=0.5&q=patna"]}>
        <Routes><Route path="/" element={<FilterHarness />} /></Routes>
      </MemoryRouter>,
    );
    expect(screen.getByLabelText(/event family/i)).toHaveValue("flood");
    expect(screen.getByLabelText(/search district/i)).toHaveValue("patna");
    expect(screen.getByRole("checkbox", { name: /alert/i })).toBeChecked();
    expect(JSON.parse(screen.getByTestId("query").textContent!)).toMatchObject({
      event_family: "flood",
      statuses: ["alert"],
      min_probability: 0.5,
      search: "patna",
    });
  });

  it("58. writes every change back to the URL so a view can be shared as a link", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter future={{ v7_relativeSplatPath: true }} initialEntries={["/"]}>
        <Routes><Route path="/" element={<FilterHarness />} /></Routes>
      </MemoryRouter>,
    );
    await user.selectOptions(screen.getByLabelText(/event family/i), "drought");
    expect(screen.getByTestId("url").textContent).toContain("family=drought");

    await user.click(screen.getByRole("checkbox", { name: /watch/i }));
    expect(screen.getByTestId("url").textContent).toContain("status=watch");
  });

  it("59. drops an out-of-range min= rather than silently filtering rows", () => {
    // A filter the user cannot see but which is excluding rows is worse than
    // no filter at all.
    render(
      <MemoryRouter future={{ v7_relativeSplatPath: true }} initialEntries={["/?min=7"]}>
        <Routes><Route path="/" element={<FilterHarness />} /></Routes>
      </MemoryRouter>,
    );
    expect(JSON.parse(screen.getByTestId("query").textContent!)).not.toHaveProperty("min_probability");
  });
});
