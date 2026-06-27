import { NextRequest, NextResponse } from "next/server";
import { DIGITAL_TWIN_SYSTEM_PROMPT } from "@/lib/persona";

const OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions";
const OPENROUTER_MODEL = "openai/gpt-oss-120b:free";
const MAX_MESSAGES = 20;
const MAX_CONTENT_LENGTH = 4000;

type ChatRole = "user" | "assistant";

type ChatMessage = {
  role: ChatRole;
  content: string;
};

type ChatRequestBody = {
  messages: ChatMessage[];
};

function isValidRole(value: unknown): value is ChatRole {
  return value === "user" || value === "assistant";
}

function normalizeMessages(input: unknown): ChatMessage[] {
  if (!Array.isArray(input)) {
    return [];
  }

  return input
    .filter((item): item is ChatMessage => {
      if (typeof item !== "object" || item === null) {
        return false;
      }

      const role = Reflect.get(item, "role");
      const content = Reflect.get(item, "content");
      return isValidRole(role) && typeof content === "string";
    })
    .map((message) => ({
      role: message.role,
      content: message.content.trim().slice(0, MAX_CONTENT_LENGTH),
    }))
    .filter((message) => message.content.length > 0)
    .slice(-MAX_MESSAGES);
}

export async function POST(request: NextRequest) {
  const apiKey = process.env.OPENROUTER_API_KEY;

  if (!apiKey) {
    return NextResponse.json(
      { error: "Missing OPENROUTER_API_KEY in environment." },
      { status: 500 },
    );
  }

  let body: ChatRequestBody;

  try {
    body = (await request.json()) as ChatRequestBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON payload." }, { status: 400 });
  }

  const messages = normalizeMessages(body?.messages);
  if (messages.length === 0) {
    return NextResponse.json(
      { error: "At least one valid message is required." },
      { status: 400 },
    );
  }

  try {
    const response = await fetch(OPENROUTER_ENDPOINT, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: OPENROUTER_MODEL,
        messages: [
          { role: "system", content: DIGITAL_TWIN_SYSTEM_PROMPT },
          ...messages,
        ],
        temperature: 0.6,
        stream: true,
      }),
    });

    if (!response.ok) {
      const details = await response.text();
      return NextResponse.json(
        {
          error:
            "The AI service is temporarily unavailable. Please try again in a moment.",
          details,
        },
        { status: 502 },
      );
    }

    if (!response.body) {
      return NextResponse.json(
        {
          error:
            "The AI service returned no stream. Please try again in a moment.",
        },
        { status: 502 },
      );
    }

    return new Response(response.body, {
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  } catch {
    return NextResponse.json(
      {
        error:
          "I cannot reach OpenRouter right now. Please retry shortly while we reconnect.",
      },
      { status: 503 },
    );
  }
}
