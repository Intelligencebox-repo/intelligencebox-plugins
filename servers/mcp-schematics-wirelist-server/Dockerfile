FROM node:20-alpine AS builder

WORKDIR /app

# System deps for PDF to image conversion and optional OCR
RUN apk add --no-cache poppler-utils tesseract-ocr

# Install dependencies
COPY package*.json tsconfig.json ./
RUN npm ci

# Build source
COPY src ./src
RUN npm run build

# Production image
FROM node:20-alpine

WORKDIR /app

# System deps needed at runtime for PDF conversion
RUN apk add --no-cache poppler-utils tesseract-ocr

COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=builder /app/dist ./dist

ENTRYPOINT ["node", "dist/index.js"]
