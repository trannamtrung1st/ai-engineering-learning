# Trung Tran AI Digital Twin Chat App

Next.js web app for professional, career-focused chat with Trung Tran's AI digital twin.

## Stack

- Next.js App Router + TypeScript
- Server-side API route for OpenRouter calls
- Model: `openai/gpt-oss-120b:free`

## Environment Variables

Create or update `.env`:

```bash
OPENROUTER_API_KEY=your_openrouter_api_key
```

## Run Locally

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Scripts

```bash
npm run dev
npm run lint
npm run build
npm run start
```

## Project Structure

- `src/app/page.tsx` - chat interface
- `src/app/api/chat/route.ts` - OpenRouter server-side endpoint
- `src/lib/persona.ts` - digital twin persona and welcome message

## Behavior Notes

- API key is kept server-side and never sent to the browser bundle.
- The assistant is intentionally guided to professional/career and engineering context.
- To tweak tone or profile details, edit `src/lib/persona.ts`.
