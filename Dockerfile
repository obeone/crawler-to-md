# syntax=docker/dockerfile:1.5
FROM python:3.12 as builder

# Set non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Define ARG for platform-specific cache separation
ARG TARGETPLATFORM

# Update and install dependencies with cache separated by architecture
RUN --mount=type=cache,target=/var/cache/apt,id=apt-cache-${TARGETPLATFORM} \
    --mount=type=cache,target=/var/lib/apt,id=apt-lib-${TARGETPLATFORM} \
    apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev

WORKDIR /app

COPY requirements.txt .

# Copy lxml wheel from the wheel directory
COPY .wheels /app/

# Conditionally install lxml from the local wheel if it exists
RUN <<EOF
if [ $(ls /app/.wheels/lxml*.whl 2> /dev/null | wc -l) -gt 0 ]; then
    echo "Installing lxml from local wheel"
    pip install /app/.wheels/lxml*.whl
else
    echo "No local wheel for lxml found, installing from PyPI"
    pip install lxml
fi
EOF

# Use pip cache to speed up builds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt -t packages


# Start from a slim Python 3.12 image for a small final image size
FROM python:3.12-slim as final

# Set non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

ARG TARGETPLATFORM

# Copy built packages from the previous stage
COPY --from=builder /app/packages /app/packages

# Update and install runtime dependencies if necessary, with cache separated by architecture
RUN --mount=type=cache,target=/var/cache/apt,id=apt-cache-${TARGETPLATFORM} \
    --mount=type=cache,target=/var/lib/apt,id=apt-lib-${TARGETPLATFORM} \
    apt-get update && apt-get install -y \
    libxml2 \
    libxslt1.1 \
    libtk8.6

WORKDIR /app

ENV PYTHONPATH=/app/packages:$PYTHONPATH

# Copy the rest of the application's source code into the working directory
COPY . .

VOLUME ["/app/cache"]

ENTRYPOINT ["python", "main.py"]
