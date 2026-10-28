# Stage 1: build the Vite production bundle
FROM node:20-alpine AS builder

WORKDIR /build

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .

# These must be passed as build args at image-build time
ARG VITE_API_URL
ARG VITE_GOOGLE_CLIENT_ID

RUN npm run build

# Stage 2: serve with nginx (rootless-friendly)
FROM nginx:1.27-alpine

# Remove default nginx site config
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/synthveda.conf

# Copy Vite build output
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:80/index.html | grep -q '<div id="root">' || exit 1

CMD ["nginx", "-g", "daemon off;"]
