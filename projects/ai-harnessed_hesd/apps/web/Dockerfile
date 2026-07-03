# Production-like web image for full-preview compose profile.
FROM node:20-alpine AS builder
WORKDIR /app

ARG VITE_API_BASE_URL=http://localhost:3001
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY packages/domain/package.json packages/domain/
COPY packages/config/package.json packages/config/

RUN npm ci --workspace @attendly/web --include-workspace-root

COPY packages/domain packages/domain
COPY packages/config packages/config
COPY apps/web apps/web

RUN npm run build -w @attendly/domain && npm run build -w @attendly/web

FROM node:20-alpine
WORKDIR /app

COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/apps/web/package.json ./apps/web/
COPY --from=builder /app/apps/web/dist ./apps/web/dist
COPY --from=builder /app/apps/web/vite.config.ts ./apps/web/

ENV PORT=3007
EXPOSE 3007

CMD ["npm", "run", "preview", "-w", "@attendly/web", "--", "--host", "0.0.0.0", "--port", "3007"]
