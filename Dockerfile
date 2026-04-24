FROM python:3.14-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

VOLUME ["/data", "/podcasts", "/config"]

ENTRYPOINT ["hathor"]
CMD ["--help"]
