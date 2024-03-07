# Use Dockerfile syntax version 1.5 for compatibility and new features
# syntax=docker/dockerfile:1.5

# Start from a lightweight Python 3.12 image to ensure a small final image size
FROM python:3.12-slim

# Set the working directory inside the container to /app
WORKDIR /app

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
