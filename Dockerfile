FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=10001:10001 . .
RUN mkdir -p /app/staticfiles /app/media \
    && chown -R 10001:10001 /app

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["sh", "./docker/entrypoint.sh"]
CMD ["gunicorn", "scportal.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--error-logfile", "-"]
