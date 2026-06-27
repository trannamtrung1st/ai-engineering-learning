 "use client";

import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DIGITAL_TWIN_WELCOME_MESSAGE } from "@/lib/persona";
import styles from "./page.module.css";

type Role = "user" | "assistant";

type Message = {
  role: Role;
  content: string;
};

export default function Home() {
  const formRef = useRef<HTMLFormElement>(null);
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: DIGITAL_TWIN_WELCOME_MESSAGE },
  ]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const content = input.trim();
    if (!content || isSending) {
      return;
    }

    const userMessage: Message = { role: "user", content };
    const assistantPlaceholder: Message = { role: "assistant", content: "" };
    const nextMessages = [...messages, userMessage, assistantPlaceholder];
    const assistantIndex = nextMessages.length - 1;

    setMessages(nextMessages);
    setInput("");
    setError("");
    setIsSending(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ messages: [...messages, userMessage] }),
      });

      if (!response.ok) {
        let errorMessage = "Something went wrong. Please try again.";
        try {
          const data = (await response.json()) as { error?: string };
          errorMessage = data.error ?? errorMessage;
        } catch {
          // keep fallback error
        }
        setError(errorMessage);
        setMessages((previous) => previous.slice(0, -1));
        return;
      }

      if (!response.body) {
        setError("Streaming response is unavailable. Please try again.");
        setMessages((previous) => previous.slice(0, -1));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let accumulated = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";

        for (const event of events) {
          const lines = event.split("\n");
          for (const line of lines) {
            if (!line.startsWith("data:")) {
              continue;
            }

            const payload = line.slice(5).trim();
            if (payload === "[DONE]") {
              continue;
            }

            try {
              const parsed = JSON.parse(payload) as {
                choices?: Array<{ delta?: { content?: string } }>;
              };
              const token = parsed.choices?.[0]?.delta?.content;

              if (!token) {
                continue;
              }

              accumulated += token;
              setMessages((previous) => {
                const updated = [...previous];
                updated[assistantIndex] = { role: "assistant", content: accumulated };
                return updated;
              });
            } catch {
              // ignore non-JSON stream events
            }
          }
        }
      }

      if (!accumulated.trim()) {
        setMessages((previous) => {
          const updated = [...previous];
          updated[assistantIndex] = {
            role: "assistant",
            content: "I could not generate a response. Please try rephrasing your request.",
          };
          return updated;
        });
      }
    } catch {
      setError("Network error. Please check your connection and retry.");
      setMessages((previous) => previous.slice(0, -1));
    } finally {
      setIsSending(false);
    }
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && event.metaKey) {
      event.preventDefault();
      formRef.current?.requestSubmit();
    }
  }

  function clearConversation() {
    if (isSending) {
      return;
    }

    setMessages([{ role: "assistant", content: DIGITAL_TWIN_WELCOME_MESSAGE }]);
    setError("");
    setInput("");
  }

  return (
    <div className={styles.page}>
      <main className={styles.container}>
        <header className={styles.header}>
          <div>
            <h1>Trung Tran AI Digital Twin</h1>
            <p>
              Career-focused and professional conversations about engineering,
              leadership, architecture, and growth.
            </p>
          </div>
          <button
            type="button"
            onClick={clearConversation}
            className={styles.clearButton}
          >
            Clear chat
          </button>
        </header>

        <section className={styles.messages} aria-live="polite">
          {messages.map((message, index) => (
            <article
              key={`${message.role}-${index}`}
              className={`${styles.message} ${
                message.role === "user" ? styles.user : styles.assistant
              }`}
            >
              <span className={styles.label}>
                {message.role === "user" ? "You" : "Digital twin"}
              </span>
              <div className={styles.markdown}>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    a: ({ ...props }) => (
                      <a {...props} target="_blank" rel="noopener noreferrer" />
                    ),
                  }}
                >
                  {message.content ||
                    (isSending &&
                    message.role === "assistant" &&
                    index === messages.length - 1
                      ? "Thinking..."
                      : "")}
                </ReactMarkdown>
              </div>
            </article>
          ))}
        </section>

        {error && (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}

        <form ref={formRef} className={styles.form} onSubmit={handleSubmit}>
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Ask about career strategy, architecture decisions, interview prep, or technical leadership..."
            className={styles.input}
            rows={3}
            disabled={isSending}
          />
          <button type="submit" className={styles.sendButton} disabled={isSending}>
            {isSending ? "Sending..." : "Send"}
          </button>
        </form>
        <p className={styles.note}>
          Responses are grounded in Trung&apos;s professional profile and intended
          for career/professional guidance.
        </p>
        <p className={styles.shortcut}>Tip: press ⌘ + Enter to send.</p>
      </main>
    </div>
  );
}
