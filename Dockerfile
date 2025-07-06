# syntax=docker/dockerfile:1

# ==============================================================================
# Base Stage: Installs uv and creates a non-root user for security
# ==============================================================================
FROM python:3.13-slim AS base

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install uv, the modern Python package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create a non-root user and group for enhanced security
RUN groupadd --system --gid 1001 app && \
    useradd --system --uid 1001 --gid 1001 -m app

# ==============================================================================
# Builder Stage: Install system and Python dependencies with optimized caching
# ==============================================================================
FROM base AS builder

# Argument for multi-platform builds
ARG TARGETPLATFORM

# CORRECTION: Argument to receive the application version from the host
ARG APP_VERSION=0.0.0

# Install build-time system dependencies using BuildKit cache mounts
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-cache-${TARGETPLATFORM} \
    --mount=type=cache,target=/var/lib/apt,sharing=locked,id=apt-cache-${TARGETPLATFORM} \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt-dev

WORKDIR /app

# Grant ownership to the non-root user before using it
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1001,gid=1001 \
    chown -R app:app /app /home/app/.cache/uv

USER app

# Copy source code BEFORE installing dependencies, as setuptools-scm needs it
COPY --chown=app:app . .

# CORRECTION: Pass the version to setuptools-scm via an environment variable
# This tells setuptools-scm to use this version string instead of looking for .git
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1001,gid=1001 \
    SETUPTOOLS_SCM_PRETEND_VERSION=${APP_VERSION} \
    uv sync

# ==============================================================================
# Final Stage: Assemble the lean production image
# ==============================================================================
FROM base AS final

WORKDIR /app

# Activate the virtual environment by adding it to the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Install only essential runtime system dependencies
ARG TARGETPLATFORM
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-cache-${TARGETPLATFORM} \
    --mount=type=cache,target=/var/lib/apt,sharing=locked,id=apt-cache-${TARGETPLATFORM} \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1

# Copy the virtual environment and source code from previous stages
# The source code is already in the builder stage, no need for another COPY . .
COPY --from=builder --chown=app:app /app /app

# This must be done as root BEFORE switching to the non-root user
RUN mkdir -p /home/app/.cache/crawler-to-md && chown -R app:app /home/app/.cache/crawler-to-md

# Switch to the non-root user for execution
USER app

VOLUME [ "/home/app/.cache/crawler-to-md" ]

ENTRYPOINT [ "/app/.venv/bin/crawler-to-md" ]
