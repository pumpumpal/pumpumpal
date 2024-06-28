FROM python:3.12.4-alpine3.20

# Set working directory inside the container
WORKDIR /pumpumpal

# Copy requirements.txt and install dependencies
COPY requirements.txt .

RUN apk add --no-cache --virtual .build-deps gcc musl-dev linux-headers git libffi-dev && \
    pip install --no-cache-dir -r requirements.txt && \
    apk del .build-deps && \
    rm -rf /var/cache/apk/* && \
    rm -rf /root/.cache/pip

COPY . .

# Set the command to run your application
CMD ["python", "-u", "main.py"]
