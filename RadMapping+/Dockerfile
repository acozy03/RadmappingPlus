# Use the official Python image.
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install -r requirements.txt


# Copy the rest of the application
COPY . .
RUN ls -R app/static && ls -l app/radmapping_service.json
# Expose the port
EXPOSE 8080

COPY app/radmapping_service.json /app/radmapping_service.json
# Set environment variables
ENV FLASK_APP=app
ENV FLASK_ENV=production
ENV PYTHONPATH=/app
ENV GCP_SERVICE_ACCOUNT_PATH=/app/radmapping_service.json
# Run the app using gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "wsgi:app"]
