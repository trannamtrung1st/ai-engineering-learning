# Production-like API image for full-preview compose profile.
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/api/package.json apps/api/
COPY packages/domain/package.json packages/domain/
COPY packages/config/package.json packages/config/

RUN npm ci --workspace @attendly/api --include-workspace-root

COPY packages/domain packages/domain
COPY packages/config packages/config
COPY apps/api apps/api
COPY scripts scripts

RUN npm run build -w @attendly/domain && npm run build -w @attendly/api

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/apps/api/package.json ./apps/api/
COPY --from=builder /app/apps/api/dist ./apps/api/dist
COPY --from=builder /app/packages/domain ./packages/domain
COPY --from=builder /app/scripts ./scripts

EXPOSE 3001
CMD ["node", "apps/api/dist/index.js"]
