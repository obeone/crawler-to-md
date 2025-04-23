#!/bin/bash

# Configuration
# Parse command line arguments
while [[ "$#" -gt 0 ]]; do
  case $1 in
    --api-key) API_KEY="$2"; shift ;;
    --api-base-url) API_BASE_URL="$2"; shift ;;
    *) echo "Unknown parameter: $1"; shift ;;
  esac
  shift
done

# Check required arguments
if [[ -z "$API_KEY" ]]; then
  echo "Error: API key is required (--api-key)"
  exit 1
fi

if [[ -z "$API_BASE_URL" ]]; then
  echo "Error: API base URL is required (--api-base-url)"
  exit 1
fi

OUTPUT_DIR="$(pwd)/output"
CACHE_DIR="$(pwd)/cache"
LOCK_FILE="/tmp/crawler_to_md.lock"
PID_FILE="/tmp/crawler_to_md.pid" # Process ID file for additional lock mechanism
LOCK_TIMEOUT=$((30 * 60)) # 30 minutes in seconds

# Function to check if a process with given PID exists and is our script
is_process_running() {
  local pid=$1
  if ps -p "$pid" > /dev/null; then
    # Get the command line of the process to verify it's our crawler script
    local cmd_line=$(ps -p "$pid" -o args= 2>/dev/null || ps -p "$pid" -o command= 2>/dev/null)
    
    # Look for crawl.sh in the command line to make sure it's our script
    if echo "$cmd_line" | grep -q "crawl.sh"; then
      return 0 # Process exists and is our script
    fi
  fi
  return 1 # Process doesn't exist or isn't our script
}

# Function to check if another instance is running
check_instance() {
  # Check PID file first
  if [ -f "$PID_FILE" ]; then
    local stored_pid=$(cat "$PID_FILE")
    if is_process_running "$stored_pid"; then
      echo "Another instance is running with PID $stored_pid. Exiting."
      return 1
    else
      echo "Found stale PID file. Previous process is no longer running."
      # Remove stale PID file
      rm -f "$PID_FILE"
    fi
  fi
  
  # Then check lock file
  if [ -f "$LOCK_FILE" ]; then
    # Get the timestamp from the lock file
    LOCK_TIMESTAMP=$(cat "$LOCK_FILE")
    CURRENT_TIMESTAMP=$(date +%s)
    
    # Calculate how long the lock has existed
    LOCK_AGE=$((CURRENT_TIMESTAMP - LOCK_TIMESTAMP))
    
    if [ $LOCK_AGE -lt $LOCK_TIMEOUT ]; then
      echo "Another instance might be running (lock file exists). Exiting."
      return 1
    else
      echo "Found stale lock file (older than $LOCK_TIMEOUT seconds). Taking over..."
      rm -f "$LOCK_FILE"
    fi
  fi
  
  return 0
}

# Function to clean up and release lock
cleanup() {
  # Only clean up if we own the locks (our PID matches the one in the PID file)
  if [ -f "$PID_FILE" ]; then
    local stored_pid=$(cat "$PID_FILE")
    if [ "$stored_pid" -eq $$ ]; then
      echo "Cleaning up and releasing locks..."
      rm -f "$LOCK_FILE"
      rm -f "$PID_FILE"
    else
      echo "Not removing lock files as they belong to another process."
    fi
  fi
}

# Set up trap to ensure lock files are removed on exit
trap cleanup EXIT INT TERM

# Check if another instance is running
if ! check_instance; then
  exit 1
fi

# Create lock file with current timestamp and PID file with current process ID
date +%s > "$LOCK_FILE"
echo $$ > "$PID_FILE"

echo "Lock acquired. Process ID: $$"

# Remove existing output and cache directories
echo "Cleaning up previous output and cache directories..."
rm -rf "$OUTPUT_DIR" "$CACHE_DIR"

# Ensure directories exist
mkdir -p "$OUTPUT_DIR" "$CACHE_DIR"

# Fetch pending crawls
echo "Fetching pending crawls..."
RESPONSE=$(curl -s -X GET \
  "${API_BASE_URL}/fetchpendingcrawls" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json")

# Parse JSON response
ERROR=$(echo "$RESPONSE" | jq -r '.error')

if [ "$ERROR" != "false" ]; then
  echo "Error fetching crawls: $RESPONSE"
  exit 1
fi

# Get the crawls array
CRAWLS=$(echo "$RESPONSE" | jq -r '.result')
CRAWL_COUNT=$(echo "$CRAWLS" | jq -r '. | length')

if [ "$CRAWL_COUNT" -eq 0 ]; then
  echo "No pending crawls found."
  exit 0
fi

echo "Processing $CRAWL_COUNT crawls..."


# Process each crawl
echo "$CRAWLS" | jq -c '.[]' | while read -r crawl; do
  # Extract crawl information
  CRAWL_ID=$(echo "$crawl" | jq -r '.id')
  CRAWL_NAME=$(echo "$crawl" | jq -r '.name')
  VECTOR_STORAGE_ID=$(echo "$crawl" | jq -r '.vector_storage_id')
  URL_ARRAY=$(echo "$crawl" | jq -r '.url') # Might be null or an array
  BASE_URL=$(echo "$crawl" | jq -r '.base_url')
  START_URL=$(echo "$crawl" | jq -r '.start_url')
  
  # Get max_pages from JSON, default to 500 if not provided
  MAX_PAGES=$(echo "$crawl" | jq -r '.max_pages // 500')

  echo "Processing crawl ID: $CRAWL_ID - $CRAWL_NAME with max pages: $MAX_PAGES"

  # Generate the title for the crawler
  TITLE="${CRAWL_ID}_crawl"
  TEMP_URL_FILE="$(pwd)/url_${CRAWL_ID}.txt" # Unique temp file per crawl

  curl -s -X POST \
    -H "X-API-KEY: ${API_KEY}" \
    -F "crawl_id=$CRAWL_ID" \
    -F "status=1" \
    -F "number_of_pages=0" \
    "${API_BASE_URL}/updatecrawlstatus"

  # Check if URL_ARRAY is a non-empty array
  if [ "$(echo "$URL_ARRAY" | jq 'if type=="array" and length > 0 then "yes" else "no" end')" == '"yes"' ]; then
    echo "Using URL list..."
    # Create temporary file with URLs
    echo "$URL_ARRAY" | jq -r '.[]' > "$TEMP_URL_FILE"
    if [ $? -ne 0 ]; then
        echo "Error creating URL file for crawl ID: $CRAWL_ID"
        # Clean up potential partial file
        rm -f "$TEMP_URL_FILE"
        # Update status to error and continue to next crawl
        curl -s -X POST \
          -H "X-API-KEY: ${API_KEY}" \
          -F "crawl_id=$CRAWL_ID" \
          -F "status=2" \
          -F "number_of_pages=0" \
          "${API_BASE_URL}/updatecrawlstatus"
        continue
    fi

    echo "Starting crawler with URL file..."
    docker run --rm \
      -v "${TEMP_URL_FILE}:/app/url.txt" \
      -v "${OUTPUT_DIR}:/app/output" \
      -v "${CACHE_DIR}:/app/cache" \
      remdex/crawler-to-md \
      --urls-file /app/url.txt \
      --title "$TITLE" \
      --max-pages "$MAX_PAGES"

    # Clean up temporary file
    rm -f "$TEMP_URL_FILE"
  elif [ -n "$BASE_URL" ] && [ -n "$START_URL" ]; then
    echo "Using Base URL: $BASE_URL and Start URL: $START_URL"
    # Run the crawler with base_url and start_url
    echo "Starting crawler..."
    docker run --rm \
      -v "${OUTPUT_DIR}:/app/output" \
      -v "${CACHE_DIR}:/app/cache" \
      remdex/crawler-to-md \
      --base-url "$BASE_URL" \
      --url "$START_URL" \
      --title "$TITLE" \
      --max-pages "$MAX_PAGES"
  fi
  
  # Check if crawler was successful
  # Use base_url to create the expected file path
  FOLDER_NAME=$(echo "$BASE_URL" | sed -e 's|^[^/]*//||' -e 's|/.*$||' | tr '.' '_')
  EXPECTED_FILE="${OUTPUT_DIR}/${FOLDER_NAME}/${TITLE}.md"
  
  # If file doesn't exist in the expected location, try alternative locations
  if [ ! -f "$EXPECTED_FILE" ]; then
    echo "File not found at primary location, searching in output directory..."
    # Look for matching file with the right title
    FOUND_FILE=$(find "$OUTPUT_DIR" -name "${TITLE}.md" -type f -print -quit)
    
    if [ -n "$FOUND_FILE" ]; then
      echo "Found file at alternative location: $FOUND_FILE"
      EXPECTED_FILE="$FOUND_FILE"
    fi
  fi

  # Check if crawler was successful
  if [ ! -f "$EXPECTED_FILE" ]; then
    echo "Crawler failed for crawl ID: $CRAWL_ID - File not found"
    STATUS=2  # Error status
    NUMBER_OF_PAGES=0
    
    # Update status for failed crawl
    curl -s -X POST \
      -H "X-API-KEY: ${API_KEY}" \
      -F "crawl_id=$CRAWL_ID" \
      -F "status=$STATUS" \
      -F "number_of_pages=$NUMBER_OF_PAGES" \
      "${API_BASE_URL}/updatecrawlstatus"
  else
    echo "Crawler completed successfully for crawl ID: $CRAWL_ID"
    STATUS=3  # Completed status
    
    # Count the number of pages (count lines with "---" which mark new pages)
    NUMBER_OF_PAGES=$(grep -c "^---$" "$EXPECTED_FILE" || echo 1)
    
    # Post the file directly using multipart/form-data
    curl -s -X POST \
      -H "X-API-KEY: ${API_KEY}" \
      -F "crawl_id=$CRAWL_ID" \
      -F "status=$STATUS" \
      -F "number_of_pages=$NUMBER_OF_PAGES" \
      -F "file=@$EXPECTED_FILE" \
      "${API_BASE_URL}/updatecrawlstatus"
  fi
  
  echo "Crawl $CRAWL_ID processing complete!"
done

echo "All crawls processed!"
