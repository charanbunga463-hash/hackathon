# API Doctor frontend (Next.js).
#
# BUILD CONTEXT IS THIS DIRECTORY (frontend/), not the repository root — see the
# matching note in backend/Dockerfile.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . ./
# Next evaluates `rewrites()` during the build and writes the result into
# .next/routes-manifest.json, so the API proxy target has to be known HERE.
# Supplying it only as a runtime environment variable leaves the manifest
# pointing at the default (127.0.0.1:8000 — the frontend container itself).
ARG NEXT_PUBLIC_API_URL=http://backend:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN addgroup -g 10002 -S nextjs && adduser -u 10002 -S nextjs -G nextjs
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs
USER nextjs
EXPOSE 3000
CMD ["npm", "run", "start"]
