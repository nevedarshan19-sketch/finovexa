import { fireEvent, render, screen } from "@testing-library/react";
import { Download } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { Button, ConfirmDialog, EmptyState, ErrorState, Modal, Skeleton } from "./ui";

describe("Button", () => {
  it("defaults to type button and fires clicks", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("type", "button");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("disables while loading and shows a spinner", () => {
    render(
      <Button loading icon={Download}>
        Export
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Export" });
    expect(button).toBeDisabled();
    expect(button.querySelector(".animate-spin")).not.toBeNull();
  });
});

describe("Modal", () => {
  it("renders nothing when closed", () => {
    render(
      <Modal open={false} onClose={() => {}} title="Hidden">
        Body
      </Modal>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders an accessible dialog and closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Approve reminder" description="Review the exact email">
        <p>Payload</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog", { name: "Approve reminder" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Review the exact email")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes from the accessible close button", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Details">
        Body
      </Modal>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("ConfirmDialog", () => {
  it("runs the confirm action and can disable it", () => {
    const onConfirm = vi.fn();
    const { rerender } = render(
      <ConfirmDialog
        open
        onClose={() => {}}
        onConfirm={onConfirm}
        title="Reset demo data?"
        confirmLabel="Reset demo"
        tone="danger"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Reset demo" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    rerender(
      <ConfirmDialog
        open
        onClose={() => {}}
        onConfirm={onConfirm}
        title="Reset demo data?"
        confirmLabel="Reset demo"
        disabled
      />,
    );
    expect(screen.getByRole("button", { name: "Reset demo" })).toBeDisabled();
  });
});

describe("state components", () => {
  it("renders an empty state with an action", () => {
    render(
      <EmptyState
        title="No approvals"
        description="Everything is reviewed."
        action={<Button size="sm">Refresh</Button>}
      />,
    );
    expect(screen.getByText("No approvals")).toBeInTheDocument();
    expect(screen.getByText("Everything is reviewed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });

  it("renders an error state with a retry action", () => {
    const retry = vi.fn();
    render(<ErrorState message="The API is unreachable." onRetry={retry} />);
    expect(screen.getByText("The API is unreachable.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("marks skeleton placeholders as decorative", () => {
    const { container } = render(<Skeleton className="h-4 w-10" />);
    const skeleton = container.firstElementChild;
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
  });
});
