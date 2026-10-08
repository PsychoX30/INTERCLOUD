import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route, useNavigate } from "react-router-dom";
import "@testing-library/jest-dom";
import PortalLayout from "./PortalLayout";
import { api } from "../../portal/api";

// The sidebar fires a notification request on mount. Stub it so the tests stay
// offline and deterministic. NOTE: CRA sets jest `resetMocks: true`, so the
// implementations are (re)installed in beforeEach — a factory-only jest.fn()
// loses its implementation before every test.
jest.mock("../../portal/api", () => ({
  __esModule: true,
  api: { get: jest.fn(), post: jest.fn() },
}));

jest.mock("../../portal/AuthContext", () => ({
  __esModule: true,
  useAuth: () => ({
    user: { role: "admin", name: "Test Admin", email: "admin@intercloud.test" },
    logout: jest.fn(),
  }),
}));

const STORAGE_KEY = "ic_admin_nav_collapsed_groups";

function TestHarness({ initialEntries = ["/portal/admin"], children }) {
  return (
    <MemoryRouter initialEntries={initialEntries} initialIndex={0}>
      <LocationProbe />
      <Routes>
        <Route path="*" element={<PortalLayout variant="admin" />} />
      </Routes>
      {children}
    </MemoryRouter>
  );
}

function NavButton({ to, label }) {
  const navigate = useNavigate();
  return (
    <button data-testid={`go-${to.replace(/\//g, "-")}`} onClick={() => navigate(to)}>
      {label}
    </button>
  );
}

function LocationProbe() {
  // Surfaces MemoryRouter's in-memory location to the DOM so tests can wait on
  // it without touching window.location (which MemoryRouter never updates).
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { useLocation } = require("react-router-dom");
  const loc = useLocation();
  return <div data-testid="location-probe">{loc.pathname}</div>;
}

describe("PortalLayout admin nav folding (behavior)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    api.get.mockResolvedValue({ data: { alerts: [], unread: 0 } });
    api.post.mockResolvedValue({});
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("F1: first click on a default-folded non-active group actually expands it", async () => {
    render(<TestHarness />);

    const toggle = await screen.findByTestId("nav-group-toggle-sales-billing");
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    // Before the fix this click wrote `!undefined === true` and stayed folded.
    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("nav-orders")).toBeVisible();
    expect(screen.getByTestId("nav-invoices")).toBeVisible();
    expect(screen.getByTestId("nav-finance")).toBeVisible();
  });

  it("second click on the same toggle folds it back", async () => {
    render(<TestHarness />);

    const toggle = await screen.findByTestId("nav-group-toggle-sales-billing");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("nav-orders")).not.toBeInTheDocument();
  });

  it("persists the explicit unfolded state across unmount/remount", async () => {
    const { unmount } = render(<TestHarness />);
    await userEvent.click(screen.getByTestId("nav-group-toggle-sales-billing"));
    expect(screen.getByTestId("nav-orders")).toBeVisible();
    unmount();

    render(<TestHarness />);
    const toggle = await screen.findByTestId("nav-group-toggle-sales-billing");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "true"));
    expect(screen.getByTestId("nav-orders")).toBeVisible();
  });

  it("auto-expands the group that owns the current route on direct entry", async () => {
    render(<TestHarness initialEntries={["/portal/admin/finance"]} />);

    const toggle = await screen.findByTestId("nav-group-toggle-sales-billing");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "true"));
    expect(screen.getByTestId("nav-finance")).toBeVisible();
  });

  it("keeps a deliberately folded active group folded while navigating within the same group", async () => {
    render(
      <TestHarness initialEntries={["/portal/admin/finance"]}>
        <NavButton to="/portal/admin/invoices" label="go invoices" />
      </TestHarness>,
    );

    const toggle = await screen.findByTestId("nav-group-toggle-sales-billing");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "true"));

    // User deliberately folds the current group.
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
    expect(screen.queryByTestId("nav-finance")).not.toBeInTheDocument();

    // Navigate to another page inside the same group.
    await userEvent.click(screen.getByTestId("go--portal-admin-invoices"));

    // Must stay folded; the old behavior re-expanded on every pathname change.
    await waitFor(() => expect(screen.getByTestId("location-probe")).toHaveTextContent("/portal/admin/invoices"));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("nav-invoices")).not.toBeInTheDocument();
  });
});
