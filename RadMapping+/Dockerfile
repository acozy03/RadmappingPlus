FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt


COPY . .
RUN ls -R app/static && ls -l app/radmapping_service.json
EXPOSE 8080

COPY app/radmapping_service.json /app/radmapping_service.json

ENV FLASK_APP=app
ENV FLASK_ENV=production
ENV PYTHONPATH=/app
ENV GCP_SERVICE_ACCOUNT_PATH=/app/radmapping_service.json

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "wsgi:app"]
