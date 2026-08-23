# Production image for the Next.js frontend — multi-stage, standalone output.
# The dev image (hot reload) is Dockerfile.dev, used by docker-compose.dev.yml.

# --- build stage ---------------------------------------------------------------
FROM node:26-alpine AS builder
WORKDIR /app

# Install from the lockfile for reproducible builds.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# NEXT_PUBLIC_* values are inlined at build time. This is the origin the browser
# uses to reach the API — with the shipped compose that's the Caddy front door,
# so REST and WebSocket calls are same-origin (no CORS). Override for your domain.
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- runtime stage -------------------------------------------------------------
FROM node:26-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# `output: "standalone"` (next.config.mjs) bundles a minimal server + only the
# node_modules it needs — no dev dependencies in the runtime image. Standalone
# output does NOT include `public/` — Next's docs require copying it manually,
# and without it every static asset (the bundled user-guide PDFs) 404s in
# production while working in dev, where the source tree is bind-mounted.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Run as the built-in unprivileged node user.
USER node

EXPOSE 3000
CMD ["node", "server.js"]
