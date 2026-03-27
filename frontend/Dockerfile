# Frontend Dockerfile для Nickelfront
# Multi-stage build: сборка + nginx

# Stage 1: Сборка
FROM node:20-alpine AS builder

WORKDIR /app

# Копируем package файлы
COPY package*.json ./

# Устанавливаем зависимости
RUN npm ci

# Копируем исходный код
COPY . .

# Собираем проект
RUN npm run build

# Stage 2: Nginx
FROM nginx:alpine

# Копируем nginx конфигурацию
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

# Копируем собранную статику
COPY --from=builder /app/dist /var/www/nickelfront/dist

# Открываем порт
EXPOSE 80

# Nginx запускается автоматически
CMD ["nginx", "-g", "daemon off;"]
