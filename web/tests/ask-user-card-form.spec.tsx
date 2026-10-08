import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AskUserOptions,
  extractAskUserPayload,
  extractMessageSegments,
} from "@/components/chat/home/AskUserOptions";
import { buildSubmitUserReply } from "@/contracts/parse/turn-command";
import type { StreamEvent } from "@/features/chat/model/protocol";
import type {
  AskUserCardData,
  AskUserQuestion,
} from "@/components/chat/home/AskUserOptions";
import { initI18n } from "@/i18n/init";

initI18n("en");

function question(
  id: string,
  prompt: string,
  labels: string[],
  overrides: Partial<AskUserQuestion> = {},
): AskUserQuestion {
  return {
    id,
    prompt,
    header: null,
    multi_select: false,
    options: labels.map((label) => ({ label, description: null })),
    allow_free_text: true,
    placeholder: null,
    ...overrides,
  };
}

function card(questions: AskUserQuestion[]): AskUserCardData {
  return {
    payload: { intro: null, questions },
    answers: null,
    resolved: false,
  };
}

const pace = question("pace", "How fast should we go?", [
  "Steady pace",
  "Deep dive",
]);

describe("opaque option identity", () => {
  const identified = question("style", "Choose a style", [], {
    options: [
      { option_id: " opaque/α:1 ", label: "Same", description: "First" },
      { option_id: "opaque:2", label: "Same", description: "Second" },
    ],
  });

  it("keeps identity through event extraction, click and submit_user_reply", async () => {
    const event: StreamEvent = {
      type: "tool_result",
      timestamp: 1,
      source: "chat",
      stage: "responding",
      content: "",
      session_id: "session-1",
      metadata: { tool_metadata: { ask_user: card([identified]).payload } },
    };
    const data = extractAskUserPayload([event])!;
    const send = vi.fn();
    const user = userEvent.setup();
    render(
      <AskUserOptions
        data={data}
        onSubmit={(reply) => {
          send(
            JSON.parse(
              JSON.stringify(
                buildSubmitUserReply({ turnId: "turn-1", ...reply }),
              ),
            ),
          );
        }}
      />,
    );
    await user.click(screen.getByRole("button", { name: /Same\s*First/ }));
    expect(
      screen.getByRole("button", { name: /Same\s*Second/ }),
    ).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(send.mock.calls[0][0]).toMatchObject({
      type: "submit_user_reply",
      turn_id: "turn-1",
      text: "Same",
      answers: [
        {
          questionId: "style",
          text: "Same",
          selected_option_id: " opaque/α:1 ",
        },
      ],
    });
    const resolved: StreamEvent = {
      ...event,
      type: "progress",
      metadata: {
        ask_user_resolved: true,
        answers: send.mock.calls[0][0].answers,
      },
    };
    expect(
      extractAskUserPayload([event, resolved])?.answers?.[0].selected_option_id,
    ).toBe(" opaque/α:1 ");
    const segment = extractMessageSegments([event, resolved]).find(
      (s) => s.kind === "ask_user",
    );
    expect(
      segment?.kind === "ask_user" &&
        segment.data.answers?.[0].selected_option_id,
    ).toBe(" opaque/α:1 ");
  });

  it("retains the pick when labels change and identified options reorder", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <AskUserOptions data={card([identified])} onSubmit={submit} />,
    );
    await user.keyboard("2");
    const renamed = {
      ...identified,
      options: [
        { ...identified.options[1], label: "Renamed" },
        { ...identified.options[0], label: "Changed" },
      ],
    };
    rerender(<AskUserOptions data={card([renamed])} onSubmit={submit} />);
    expect(screen.getByRole("button", { name: /Renamed/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenCalledWith({
      text: "Renamed",
      answers: [
        {
          questionId: "style",
          text: "Renamed",
          selected_option_id: "opaque:2",
        },
      ],
    });
  });

  it.each(["free text", "skip"])(
    "does not assign a choice identity to %s",
    async (mode) => {
      const submit = vi.fn();
      const user = userEvent.setup();
      render(<AskUserOptions data={card([identified])} onSubmit={submit} />);
      await user.keyboard("1");
      if (mode === "free text") {
        await user.click(
          screen.getByRole("button", { name: /Something else/ }),
        );
        await user.type(screen.getByRole("textbox"), "Same");
        await user.click(screen.getByRole("button", { name: "Submit" }));
      } else {
        await user.click(screen.getByRole("button", { name: "Skip" }));
      }
      expect(submit.mock.calls[0][0].answers).toEqual([
        { questionId: "style", text: mode === "free text" ? "Same" : "" },
      ]);
    },
  );

  it("preserves multi-select text replies without claiming a single identity", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(
      <AskUserOptions
        data={card([{ ...identified, multi_select: true }])}
        onSubmit={submit}
      />,
    );
    await user.keyboard("12");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenCalledWith({
      text: "Same, Same",
      answers: [{ questionId: "style", text: "Same, Same" }],
    });
  });
});

describe("picking an option by its number", () => {
  it("preserves a legacy selected label across reorder without creating an ID", async () => {
    const legacy = question("legacy", "Choose a style", ["A", "B"]);
    expect(
      legacy.options.every((option) => option.option_id === undefined),
    ).toBe(true);
    const submit = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <AskUserOptions data={card([legacy])} onSubmit={submit} />,
    );
    await user.click(screen.getByRole("button", { name: /B$/ }));
    const reordered = {
      ...legacy,
      options: [legacy.options[1], legacy.options[0]],
    };
    rerender(<AskUserOptions data={card([reordered])} onSubmit={submit} />);
    expect(screen.getByRole("button", { name: /B$/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /A$/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenCalledWith({
      text: "B",
      answers: [{ questionId: "legacy", text: "B" }],
    });
    expect(submit.mock.calls[0][0].answers[0]).not.toHaveProperty(
      "selected_option_id",
    );
  });

  it("selects the row carrying that number, and still waits for Submit", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={submit} />);

    await user.keyboard("2");
    expect(screen.getByRole("button", { name: /Deep dive/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // The number picks; it does not answer for the user.
    expect(submit).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(submit).toHaveBeenCalledWith({
      text: "Deep dive",
      answers: [{ questionId: "pace", text: "Deep dive" }],
    });
  });

  it("ignores a number no option carries", async () => {
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={vi.fn()} />);

    await user.keyboard("7");
    for (const label of [/Steady pace/, /Deep dive/]) {
      expect(screen.getByRole("button", { name: label })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    }
  });

  it("leaves the digit alone once the user is writing their own reply", async () => {
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /Something else/ }));
    await user.keyboard("2");

    // The keystroke belongs to the box that has focus, not to the list.
    expect(screen.getByRole("textbox")).toHaveValue("2");
    expect(screen.getByRole("button", { name: /Deep dive/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

describe("declining a question", () => {
  it("submits the only question empty, which the backend reads as skipped", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={submit} />);

    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(submit).toHaveBeenCalledWith({
      text: "",
      answers: [{ questionId: "pace", text: "" }],
    });
  });

  it("drops the pick it just cleared rather than sending it as the answer", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(<AskUserOptions data={card([pace])} onSubmit={submit} />);

    await user.keyboard("1");
    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(submit).toHaveBeenCalledWith({
      text: "",
      answers: [{ questionId: "pace", text: "" }],
    });
  });

  it("walks forward through a multi-question card and submits at the end", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    const depth = question("depth", "How deep?", ["Overview", "Everything"], {
      header: "Depth",
    });
    render(<AskUserOptions data={card([pace, depth])} onSubmit={submit} />);

    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(screen.getByText("How deep?")).toBeVisible();
    expect(submit).not.toHaveBeenCalled();

    // Nothing left to move on to, so declining the last one finishes the card
    // instead of bouncing back to the question already declined.
    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(submit).toHaveBeenCalledWith({
      text: "",
      answers: [
        { questionId: "pace", text: "" },
        { questionId: "depth", text: "" },
      ],
    });
  });
});

describe("the shape of the card", () => {
  it("draws one rule, between the answering area and the controls", () => {
    const { container } = render(
      <AskUserOptions data={card([pace])} onSubmit={vi.fn()} />,
    );

    // Writing your own answer is one more way to answer, so it reads as the
    // last row of the list rather than a band behind a rule of its own. That
    // leaves exactly one rule in the card: the one under everything you can
    // answer with, above the controls that end the question.
    const rules = container.querySelectorAll('[class*="border-t"]');
    expect(rules).toHaveLength(1);
    const rule = rules[0];
    for (const name of ["Steady pace", "Something else…"]) {
      const row = screen.getByRole("button", { name: new RegExp(name) });
      expect(
        row.compareDocumentPosition(rule) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
    // Declining and answering both end the question, so Skip sits with Submit.
    expect(rule.contains(screen.getByRole("button", { name: "Skip" }))).toBe(
      true,
    );
    expect(rule.contains(screen.getByRole("button", { name: "Submit" }))).toBe(
      true,
    );
  });
});

describe("the answered card", () => {
  it("is the question, greyed, with the answer under it — no heading to open", () => {
    render(
      <AskUserOptions
        data={{
          payload: { intro: null, questions: [pace] },
          answers: [{ questionId: "pace", text: "Deep dive" }],
          resolved: true,
        }}
        onSubmit={vi.fn()}
      />,
    );

    const answered = screen.getByTestId("ask-user-answers");
    expect(answered).toHaveTextContent("How fast should we go?");
    expect(answered).toHaveTextContent("Deep dive");
    // Two lines are not worth a disclosure: nothing to expand, nothing to
    // count.
    expect(screen.queryByText("Your answers")).toBeNull();
    expect(answered.querySelector("button")).toBeNull();
  });

  it("says a skipped question was skipped", () => {
    render(
      <AskUserOptions
        data={{
          payload: { intro: null, questions: [pace] },
          answers: [{ questionId: "pace", text: "" }],
          resolved: true,
        }}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByTestId("ask-user-answers")).toHaveTextContent(
      "(skipped)",
    );
  });

  it("keeps the disclosure for the surface that asked for one", async () => {
    const user = userEvent.setup();
    render(
      <AskUserOptions
        data={{
          payload: { intro: null, questions: [pace] },
          answers: [{ questionId: "pace", text: "Deep dive" }],
          resolved: true,
        }}
        onSubmit={vi.fn()}
        collapsible
        defaultCollapsed
      />,
    );

    expect(screen.queryByText("Deep dive")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Your answers/ }));
    expect(screen.getByText("Deep dive")).toBeVisible();
  });
});
