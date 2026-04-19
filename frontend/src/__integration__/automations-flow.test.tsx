import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import App from "@/App";
import { renderWithProviders } from "@/test/utils";

function getJobRow(jobName: string): HTMLElement {
	const cell = screen.getByText(jobName);
	const row = cell.closest("tr");
	if (!row) {
		throw new Error(`Row for job '${jobName}' not found`);
	}
	return row;
}

describe("automations page integration", () => {
	beforeEach(() => {
		window.history.pushState({}, "", "/automations");
	});

	it("navigates to automations from the header navigation", async () => {
		const user = userEvent.setup();
		window.history.pushState({}, "", "/dashboard");
		renderWithProviders(<App />);

		await user.click(await screen.findByRole("link", { name: "Automations" }));

		expect(await screen.findByRole("heading", { name: "Automations" })).toBeInTheDocument();
		expect(window.location.pathname).toBe("/automations");
	});

	it("validates form input, creates a job, updates it, and renders run history", async () => {
		const user = userEvent.setup();
		renderWithProviders(<App />);

		expect(await screen.findByRole("heading", { name: "Automations" })).toBeInTheDocument();
		expect(await screen.findByText("No automations")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Add automation" }));

		expect(await screen.findByRole("heading", { name: "Add automation" })).toBeInTheDocument();
		expect(screen.getByRole("heading", { name: "Basics" })).toBeInTheDocument();
		expect(screen.getByRole("heading", { name: "Schedule" })).toBeInTheDocument();
		expect(screen.getByRole("heading", { name: "Content / Execution" })).toBeInTheDocument();

		await user.type(screen.getByPlaceholderText("Automation name"), "Daily smoke ping");
		await user.click(screen.getByRole("button", { name: "Accounts" }));
		await user.click(await screen.findByRole("menuitemcheckbox", { name: "primary@example.com" }));
		await user.keyboard("{Escape}");

		await user.click(screen.getByRole("button", { name: "Create automation" }));

		expect(await screen.findByText("Daily smoke ping")).toBeInTheDocument();
		expect(screen.getByText("Runs will appear here after automation jobs execute.")).toBeInTheDocument();

		await user.click(within(getJobRow("Daily smoke ping")).getByRole("switch"));
		await waitFor(() => {
			expect(within(getJobRow("Daily smoke ping")).getByText("Disabled")).toBeInTheDocument();
		});

		await user.click(within(getJobRow("Daily smoke ping")).getByRole("button", { name: "Edit Daily smoke ping" }));
		expect(await screen.findByRole("heading", { name: "Edit automation" })).toBeInTheDocument();
		const nameInput = screen.getByLabelText("Name");
		await user.clear(nameInput);
		await user.type(nameInput, "Daily smoke ping edited");
		await user.click(screen.getByRole("button", { name: "Save changes" }));
		expect(await screen.findByText("Daily smoke ping edited")).toBeInTheDocument();

		await user.click(within(getJobRow("Daily smoke ping edited")).getByRole("button", { name: "Run now Daily smoke ping edited" }));
		expect(await screen.findByRole("alertdialog", { name: "Run automation now" })).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Run now" }));

		const recentRunsSection = screen.getByRole("heading", { name: "Recent runs" }).closest("section");
		if (!recentRunsSection) {
			throw new Error("Recent runs section not found");
		}
		expect(await within(recentRunsSection).findByText("manual")).toBeInTheDocument();
		expect(await within(recentRunsSection).findByText("success")).toBeInTheDocument();
		await waitFor(() => {
			expect(screen.queryByText("Runs will appear here after automation jobs execute.")).not.toBeInTheDocument();
		});
	});

	it("creates automation with default all-accounts selection", async () => {
		const user = userEvent.setup();
		renderWithProviders(<App />);

		expect(await screen.findByRole("heading", { name: "Automations" })).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Add automation" }));
		await user.type(screen.getByPlaceholderText("Automation name"), "All accounts job");
		await user.click(screen.getByRole("button", { name: "Create automation" }));

		const row = getJobRow("All accounts job");
		expect(within(row).getByText("All accounts")).toBeInTheDocument();
		expect(screen.queryByText("No accounts available. Add at least one account.")).not.toBeInTheDocument();
	});
});
