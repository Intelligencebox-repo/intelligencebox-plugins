# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files
COPY package.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY tsconfig.json ./
COPY src/ ./src/

# Build TypeScript
RUN npm run build

# Production stage
FROM node:22-alpine

WORKDIR /app

# Copy package files and install production dependencies only
COPY package.json ./
RUN npm install --omit=dev

# Copy built files
COPY --from=builder /app/dist ./dist

# Set default environment variables
ENV BOX_SERVER_URL=http://host.docker.internal:3001
ENV METADATA_QUERY_ENDPOINT=/api/metadata/query
ENV NODE_ENV=production

# Run the server
ENTRYPOINT ["node", "dist/index.js"]
