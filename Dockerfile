# Use Dockerfile syntax version 1.5 for compatibility and new features
# syntax=docker/dockerfile:1.5

FROM python:3.12 as builder

# Remove docker clean process
RUN rm /etc/apt/apt.conf.d/docker-clean

# Set non interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Update and install dependencies
RUN --mount=type=cache,target=/var/cache/apt --mount=type=cache,target=/var/lib/apt \
    apt-get update && \
    apt-get install -y libxml2-dev libxslt-dev

WORKDIR /app

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache \
    pip install -r requirements.txt -t packages

# Start from a lightweight Python 3.12 image to ensure a small final image size
FROM python:3.12-slim as final


# Copy built packages from the previous stage (Do it first to force that the building of this stage wait for the previous stage to finish and avoid a race condition)
COPY --from=builder /app/packages /app/packages

# Remove docker clean process
RUN rm /etc/apt/apt.conf.d/docker-clean

# Set non interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Update and install dependencies
RUN --mount=type=cache,target=/var/cache/apt --mount=type=cache,target=/var/lib/apt \
    apt-get update && \
    apt-get install -y libxml2 libxslt1.1

# Set the working directory inside the container to /app
WORKDIR /app

ENV PYTHONPATH=/app/packages:$PYTHONPATH

# Copy the requirements.txt file into the working directory
COPY requirements.txt .

# Install dependencies from requirements.txt using pip
# Utilize Docker's cache mount feature to speed up builds by caching pip's cache directory
RUN --mount=type=cache,target=/root/.cache \
    pip install -r requirements.txt

# Copy the rest of the application's source code into the working directory
COPY . .

# Declare a volume at /app/cache to allow for caching or persisting data outside of the container
VOLUME [ "/app/cache"]

# Set the container's entrypoint to run the main Python application
ENTRYPOINT [ "python", "main.py" ]

