# Use Python 3.11 slim image as base
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Update package index and install system dependencies
# Using retries for better reliability with network issues
RUN apt-get update || apt-get update || apt-get update
RUN apt-get install -y --no-install-recommends \
        default-mysql-client \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy requirements first for better caching
COPY server/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server/ .

# Copy default background images to a template location
RUN mkdir -p /app/backgrounds-defaults
COPY www/images/backgrounds/ /app/backgrounds-defaults/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app

# Copy default background images and set up the backgrounds directory
RUN mkdir -p /var/www/images/backgrounds \
    && cp -r /app/backgrounds-defaults/* /var/www/images/backgrounds/ \
    && chown -R app:app /var/www/images \
    && chmod 755 /var/www/images \
    && chmod 755 /var/www/images/backgrounds

# Fix line endings and make startup script executable
RUN sed -i 's/\r$//' startup.sh \
    && chmod +x startup.sh \
    && chmod -R u+w /app \
    && chown -R app:app /app

USER app

# Expose the port Flask runs on
EXPOSE 5000

# Command to run the application
CMD ["./startup.sh"]