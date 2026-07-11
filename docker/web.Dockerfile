# Build the SPA, serve the static bundle via nginx (which also proxies the API).
FROM node:22-alpine AS build
WORKDIR /app
COPY packages/kortex-web/package.json packages/kortex-web/package-lock.json ./
RUN npm ci
COPY packages/kortex-web/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/web-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
