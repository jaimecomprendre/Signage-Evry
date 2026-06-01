FROM python:3.11-slim

# Install watchdog and any other dependencies
RUN pip install watchdog

# Copy the watcher script
COPY generate_feed.py /app/generate_feed.py

WORKDIR /app

# Run the watcher
CMD ["python", "generate_feed.py"]