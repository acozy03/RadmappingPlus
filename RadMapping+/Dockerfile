FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt


COPY . .
RUN ls -R app/static
EXPOSE 8080


ENV FLASK_APP=app
ENV FLASK_ENV=production
ENV PYTHONPATH=/app

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "wsgi:app"]
