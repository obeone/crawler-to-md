# Use Dockerfile syntax version 1.5 for compatibility and new features
# syntax=docker/dockerfile:1.5

FROM python:3.12 as builder

# Set non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Prevent docker from cleaning up the apt cache
RUN rm -f /etc/apt/apt.conf.d/docker-clean

# Define ARG for platform-specific cache separation
ARG TARGETPLATFORM

# Update and install dependencies with cache separated by architecture
RUN --mount=type=cache,target=/var/cache/apt,id=apt-cache-${TARGETPLATFORM} \
    --mount=type=cache,target=/var/lib/apt,id=apt-lib-${TARGETPLATFORM} \
    apt-get update && \
    apt-get install -y libxml2-dev libxslt-dev

WORKDIR /app

COPY requirements.txt .

# Use pip cache to speed up builds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt -t packages

# Start from a slim Python 3.12 image for a small final image size
FROM python:3.12-slim as final

# Set non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Prevent docker from cleaning up the apt cache in the final image
RUN rm -f /etc/apt/apt.conf.d/docker-clean

ARG TARGETPLATFORM

# Copy built packages from the previous stage
COPY --from=builder /app/packages /app/packages

# Update and install runtime dependencies if necessary, with cache separated by architecture
RUN --mount=type=cache,target=/var/cache/apt,id=apt-cache-${TARGETPLATFORM} \
    --mount=type=cache,target=/var/lib/apt,id=apt-lib-${TARGETPLATFORM} \
    apt-get update && \
    apt-get install -y libxml2 libxslt1.1

WORKDIR /app

ENV PYTHONPATH=/app/packages:$PYTHONPATH

COPY requirements.txt .

# Install dependencies from requirements.txt using pip and cache
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy the rest of the application's source code into the working directory
COPY . .

VOLUME [ "/app/cache"]

ENTRYPOINT [ "python", "main.py" ]
