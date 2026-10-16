# Edge: serves the built SPA, reverse-proxies the API, and serves protected
# HLS files via X-Accel-Redirect (the API authorises, nginx streams).
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY openapi/ /openapi/
# vite.config.js reads the SPA's security headers (preview) from the same file nginx includes.
COPY deploy/nginx/security-headers.conf /deploy/nginx/security-headers.conf
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/nginx/security-headers.conf /etc/nginx/snippets/neotv-security-headers.conf
COPY --from=frontend /build/dist /usr/share/nginx/html
